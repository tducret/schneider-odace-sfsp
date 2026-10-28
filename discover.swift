import Foundation
import CoreBluetooth

func emit(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
    fflush(stdout)
}

final class Discovery: NSObject, CBCentralManagerDelegate {
    var manager: CBCentralManager!
    var seen: Set<String> = []

    override init() {
        super.init()
        manager = CBCentralManager(delegate: self, queue: nil)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else {
            emit(["status": "unavailable", "state": central.state.rawValue])
            return
        }
        central.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: true])
        emit(["status": "scanning"])
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData ad: [String: Any], rssi RSSI: NSNumber) {
        let id = peripheral.identifier.uuidString
        let name = ad[CBAdvertisementDataLocalNameKey] as? String ?? peripheral.name ?? ""
        let mfg = (ad[CBAdvertisementDataManufacturerDataKey] as? Data)?.map { String(format: "%02x", $0) }.joined() ?? ""
        let services = (ad[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []).map { $0.uuidString }
        let serviceData = (ad[CBAdvertisementDataServiceDataKey] as? [CBUUID: Data] ?? [:]).reduce(into: [String: String]()) {
            $0[$1.key.uuidString] = $1.value.map { String(format: "%02x", $0) }.joined()
        }
        // Log once per device/name/service set, and whenever Schneider's payload changes.
        let signature = id + name + services.joined() + (mfg.hasPrefix("b602") ? mfg : "")
        guard seen.insert(signature).inserted else { return }
        emit(["id": id, "name": name, "manufacturer_data": mfg,
              "services": services, "service_data": serviceData,
              "connectable": ad[CBAdvertisementDataIsConnectable] as? Bool ?? false,
              "rssi": RSSI, "timestamp": ISO8601DateFormatter().string(from: Date())])
    }
}

let discovery = Discovery()
let seconds = CommandLine.arguments.count > 1 ? Double(CommandLine.arguments[1]) ?? 30 : 30
RunLoop.main.run(until: Date(timeIntervalSinceNow: seconds))
discovery.manager.stopScan()
emit(["status": "finished"])
