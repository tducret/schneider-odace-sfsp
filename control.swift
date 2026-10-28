import Foundation
import CoreBluetooth

func emit(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
    fflush(stdout)
}

final class Control: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    let target: UUID
    let command: UInt8
    let serviceID = CBUUID(string: "720A9080-9C7D-11E5-A7E3-0002A5D5C51B")
    let stateID = CBUUID(string: "720A9081-9C7D-11E5-A7E3-0002A5D5C51B")
    var manager: CBCentralManager!
    var device: CBPeripheral?
    var finished = false
    var wrote = false

    init(target: UUID, command: UInt8) {
        self.target = target
        self.command = command
        super.init()
        manager = CBCentralManager(delegate: self, queue: nil)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else {
            emit(["status": "bluetooth_unavailable", "state": central.state.rawValue])
            finished = true
            return
        }
        emit(["status": "scanning_for_target", "id": target.uuidString])
        central.scanForPeripherals(withServices: nil)
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard peripheral.identifier == target, device == nil else { return }
        central.stopScan()
        device = peripheral
        peripheral.delegate = self
        emit(["status": "connecting", "rssi": RSSI])
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        emit(["status": "connected", "id": peripheral.identifier.uuidString])
        peripheral.discoverServices([serviceID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        emit(["status": "connection_failed", "error": error?.localizedDescription ?? ""])
        finished = true
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == serviceID }) else {
            emit(["status": "service_failed", "error": error?.localizedDescription ?? "not found"])
            finished = true
            return
        }
        peripheral.discoverCharacteristics([stateID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard error == nil, let characteristic = service.characteristics?.first(where: { $0.uuid == stateID }),
              characteristic.properties.contains(.write) else {
            emit(["status": "characteristic_failed", "error": error?.localizedDescription ?? "not writable"])
            finished = true
            return
        }
        // Exactly one write, to the on/off characteristic only; no retries or configuration changes.
        wrote = true
        emit(["status": "sending", "value": command, "id": target.uuidString])
        peripheral.writeValue(Data([command]), for: characteristic, type: .withResponse)
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        emit(["status": error == nil ? "write_acknowledged" : "write_failed",
              "error": error?.localizedDescription ?? "", "id": target.uuidString])
        guard error == nil else { finished = true; return }
        peripheral.readValue(for: characteristic)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        emit(["status": "readback", "value": characteristic.value?.map { String(format: "%02x", $0) }.joined() ?? "",
              "error": error?.localizedDescription ?? ""])
        finished = true
    }

    func stop() {
        manager.stopScan()
        if let device = device { manager.cancelPeripheralConnection(device) }
    }
}

guard (3...4).contains(CommandLine.arguments.count),
      let target = UUID(uuidString: CommandLine.arguments[1]),
      ["on", "off"].contains(CommandLine.arguments[2]) else {
    fputs("Usage: swift control.swift MACOS_DEVICE_UUID on|off [timeout_seconds]\n", stderr)
    exit(2)
}
let controller = Control(target: target, command: CommandLine.arguments[2] == "on" ? 1 : 0)
let duration = CommandLine.arguments.count == 4 ? Double(CommandLine.arguments[3]) ?? 25 : 25
let deadline = Date(timeIntervalSinceNow: duration)
while !controller.finished && Date() < deadline {
    RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.1))
}
if !controller.finished { emit(["status": "timeout", "write_attempted": controller.wrote]) }
controller.stop()
RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.5))
