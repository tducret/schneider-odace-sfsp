import Foundation
import CoreBluetooth

func emit(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
    fflush(stdout)
}

final class Inspector: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    var manager: CBCentralManager!
    var devices: [UUID: CBPeripheral] = [:]
    let targets: Set<UUID>

    init(targets: Set<UUID>) {
        self.targets = targets
        super.init()
        manager = CBCentralManager(delegate: self, queue: nil)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else { return }
        central.scanForPeripherals(withServices: nil)
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData ad: [String: Any], rssi RSSI: NSNumber) {
        let name = ad[CBAdvertisementDataLocalNameKey] as? String ?? peripheral.name ?? ""
        guard targets.contains(peripheral.identifier), devices[peripheral.identifier] == nil else { return }
        devices[peripheral.identifier] = peripheral
        peripheral.delegate = self
        emit(["status": "connecting", "name": name, "id": peripheral.identifier.uuidString])
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        emit(["status": "connected", "name": peripheral.name ?? ""])
        peripheral.discoverServices(nil)
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        emit(["status": "connection_failed", "name": peripheral.name ?? "", "error": error?.localizedDescription ?? ""])
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error = error {
            emit(["error": error.localizedDescription, "name": peripheral.name ?? ""])
            return
        }
        for service in peripheral.services ?? [] {
            emit(["name": peripheral.name ?? "", "service": service.uuid.uuidString])
            peripheral.discoverCharacteristics(nil, for: service)
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let error = error {
            emit(["error": error.localizedDescription, "name": peripheral.name ?? ""])
            return
        }
        for characteristic in service.characteristics ?? [] {
            let p = characteristic.properties
            emit(["name": peripheral.name ?? "", "service": service.uuid.uuidString,
                  "characteristic": characteristic.uuid.uuidString,
                  "read": p.contains(.read), "write": p.contains(.write),
                  "write_without_response": p.contains(.writeWithoutResponse),
                  "notify": p.contains(.notify), "indicate": p.contains(.indicate)])
            // Only read standard Device Information values, not proprietary registers.
            if service.uuid == CBUUID(string: "180A") && p.contains(.read) {
                peripheral.readValue(for: characteristic)
            }
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        emit(["name": peripheral.name ?? "", "characteristic": characteristic.uuid.uuidString,
              "value": characteristic.value?.map { String(format: "%02x", $0) }.joined() ?? "",
              "text": characteristic.value.flatMap { String(data: $0, encoding: .utf8) } ?? "",
              "error": error?.localizedDescription ?? ""])
    }

    func stop() {
        manager.stopScan()
        for peripheral in devices.values { manager.cancelPeripheralConnection(peripheral) }
    }
}

let arguments = Array(CommandLine.arguments.dropFirst())
let targets = arguments.compactMap { UUID(uuidString: $0) }
guard !targets.isEmpty, targets.count == arguments.count else {
    fputs("Usage: swift inspect.swift MACOS_DEVICE_UUID [MACOS_DEVICE_UUID ...]\n", stderr)
    exit(2)
}
let inspector = Inspector(targets: Set(targets))
RunLoop.main.run(until: Date(timeIntervalSinceNow: 35))
inspector.stop()
RunLoop.main.run(until: Date(timeIntervalSinceNow: 1))
