import Foundation
import CoreBluetooth

// Native macOS, receive-only scanner. No pairing or connection is made.
func emit(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
    fflush(stdout)
}

final class Scanner: NSObject, CBCentralManagerDelegate {
    var manager: CBCentralManager!
    var advertisements = 0
    var matches = 0
    let actions = ["off", "on", "toggle", "dim_up", "dim_down", "up", "down", "stop", "scene_user", "scene_in", "scene_out"]

    override init() {
        super.init()
        manager = CBCentralManager(delegate: self, queue: nil)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else {
            emit(["status": "bluetooth_unavailable", "state": central.state.rawValue,
                  "authorization": CBManager.authorization.rawValue])
            return
        }
        central.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: true])
        emit(["status": "ready", "message": "Press the Odace switch now"])
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        advertisements += 1
        guard let data = advertisementData[CBAdvertisementDataManufacturerDataKey] as? Data else { return }
        let bytes = Array(data)
        guard bytes.count >= 12, Array(bytes.prefix(4)) == [0xb6, 0x02, 0x8e, 0x44] else { return }
        matches += 1
        let uid = bytes[7...9].reversed().map { String(format: "%02x", $0) }.joined()
        let code = Int(bytes[11])
        emit(["timestamp": ISO8601DateFormatter().string(from: Date()),
              "uid": uid, "action_code": code,
              "action": code < actions.count ? actions[code] : "unknown",
              "manufacturer_data": bytes.map { String(format: "%02x", $0) }.joined(),
              "macos_identifier": peripheral.identifier.uuidString, "rssi": RSSI])
    }
}

let scanner = Scanner()
let duration = CommandLine.arguments.count > 1 ? Double(CommandLine.arguments[1]) ?? 180 : 180
RunLoop.main.run(until: Date(timeIntervalSinceNow: duration))
scanner.manager.stopScan()
emit(["status": "finished", "advertisements": scanner.advertisements, "matching_advertisements": scanner.matches])
