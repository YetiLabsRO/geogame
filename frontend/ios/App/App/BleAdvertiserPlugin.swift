import Foundation
import Capacitor
import CoreBluetooth

/// Advertises the player's ephemeral proximity token for the Dementors BLE mode.
///
/// LIMITATION (iOS): unlike Android's `BluetoothLeAdvertiser.addServiceData`, CoreBluetooth's
/// `CBPeripheralManager.startAdvertising` accepts only `CBAdvertisementDataLocalNameKey` and
/// `CBAdvertisementDataServiceUUIDsKey` — it cannot put arbitrary service DATA into the
/// advertisement packet itself. So this plugin advertises only the game's service UUID and
/// publishes the token as the value of a readable characteristic on a `CBMutableService` with
/// that same UUID. A scanning peer therefore cannot read the token straight from the
/// advertisement (as it can on Android) — it has to connect as a central and read the
/// characteristic. `BleProximityService`/the scan side (`@capacitor-community/bluetooth-le`)
/// needs to account for this asymmetry when talking to an iOS advertiser; see
/// `docs/mobile.md` for the full explanation and status.
///
/// UNVERIFIED — written without Xcode or a Mac available in this environment. It has not been
/// compiled or run. Build and test on macOS before relying on it; see `openspec/changes/
/// mobile-app/design.md` decision D4 (BLE part) and `mode-dementors-ble` for the iOS pilot gate.
@objc(BleAdvertiserPlugin)
public class BleAdvertiserPlugin: CAPPlugin, CAPBridgedPlugin, CBPeripheralManagerDelegate {
    public let identifier = "BleAdvertiserPlugin"
    public let jsName = "BleAdvertiser"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise)
    ]

    // Fixed characteristic UUID that carries the token; distinct from the (caller-supplied)
    // game service UUID so it never collides with it.
    private static let tokenCharacteristicUUID = CBUUID(string: "7A9E9F9C-1B7B-4E33-9C90-6B7F6F6E9A31")

    private var peripheralManager: CBPeripheralManager?
    private var pendingStartCall: CAPPluginCall?
    private var pendingServiceUUID: CBUUID?
    private var pendingTokenData: Data?

    @objc func isSupported(_ call: CAPPluginCall) {
        let manager = peripheralManager ?? CBPeripheralManager(delegate: nil, queue: nil,
                                                                 options: [CBPeripheralManagerOptionShowPowerAlertKey: false])
        // .unsupported is the only state that means "no BLE peripheral/advertising role at
        // all"; poweredOff/unauthorized still mean the hardware exists (just not usable yet).
        call.resolve(["supported": manager.state != .unsupported])
    }

    @objc func start(_ call: CAPPluginCall) {
        guard let serviceUuidString = call.getString("serviceUuid"), !serviceUuidString.isEmpty else {
            call.reject("serviceUuid is required")
            return
        }
        guard let token = call.getString("token"), !token.isEmpty else {
            call.reject("token is required")
            return
        }
        guard let tokenData = token.data(using: .utf8), tokenData.count <= 16 else {
            call.reject("token must be at most 16 bytes when UTF-8 encoded")
            return
        }

        stopAdvertisingInternal()

        pendingStartCall = call
        pendingServiceUUID = CBUUID(string: serviceUuidString)
        pendingTokenData = tokenData

        if peripheralManager == nil {
            peripheralManager = CBPeripheralManager(delegate: self, queue: nil)
            // beginAdvertising() runs from peripheralManagerDidUpdateState once the new
            // manager reports .poweredOn.
        } else if peripheralManager?.state == .poweredOn {
            beginAdvertising()
        }
        // Otherwise we wait for the next peripheralManagerDidUpdateState callback.
    }

    @objc func stop(_ call: CAPPluginCall) {
        stopAdvertisingInternal()
        call.resolve()
    }

    private func beginAdvertising() {
        guard let manager = peripheralManager, manager.state == .poweredOn,
              let serviceUUID = pendingServiceUUID, let tokenData = pendingTokenData else {
            return
        }

        let characteristic = CBMutableCharacteristic(
            type: BleAdvertiserPlugin.tokenCharacteristicUUID,
            properties: [.read],
            value: tokenData,
            permissions: [.readable]
        )
        let service = CBMutableService(type: serviceUUID, primary: true)
        service.characteristics = [characteristic]

        manager.removeAllServices()
        manager.add(service)
        // Advertising starts once didAdd(service:) confirms the service was registered
        // successfully (see the CBPeripheralManagerDelegate callback below), so pendingStartCall
        // is resolved there rather than here.
    }

    private func stopAdvertisingInternal() {
        peripheralManager?.stopAdvertising()
        peripheralManager?.removeAllServices()
        pendingServiceUUID = nil
        pendingTokenData = nil
        pendingStartCall = nil
    }

    // MARK: - CBPeripheralManagerDelegate

    public func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        switch peripheral.state {
        case .poweredOn:
            if pendingServiceUUID != nil {
                beginAdvertising()
            }
        case .unauthorized:
            pendingStartCall?.reject("Bluetooth permission was denied")
            pendingStartCall = nil
        case .unsupported:
            pendingStartCall?.reject("BLE peripheral/advertising is not supported on this device")
            pendingStartCall = nil
        case .poweredOff, .resetting, .unknown:
            break // wait for a further state update; nothing actionable yet
        @unknown default:
            break
        }
    }

    public func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        if let error = error {
            pendingStartCall?.reject("Failed to register BLE service: \(error.localizedDescription)")
            pendingStartCall = nil
            return
        }
        guard let serviceUUID = pendingServiceUUID else { return }
        peripheral.startAdvertising([
            CBAdvertisementDataServiceUUIDsKey: [serviceUUID]
        ])
        pendingStartCall?.resolve()
        pendingStartCall = nil
    }

    public func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveRead request: CBATTRequest) {
        guard request.characteristic.uuid == BleAdvertiserPlugin.tokenCharacteristicUUID,
              let tokenData = pendingTokenData else {
            peripheral.respond(to: request, withResult: .attributeNotFound)
            return
        }
        guard request.offset <= tokenData.count else {
            peripheral.respond(to: request, withResult: .invalidOffset)
            return
        }
        request.value = tokenData.subdata(in: request.offset..<tokenData.count)
        peripheral.respond(to: request, withResult: .success)
    }
}
