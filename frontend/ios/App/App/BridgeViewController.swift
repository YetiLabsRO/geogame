import Capacitor

/// Custom bridge view controller so locally-defined plugins (ones that aren't installed
/// npm packages with their own podspec/Package.swift target, e.g. `BleAdvertiserPlugin`) get
/// registered with the bridge. See Capacitor's "Custom Native iOS Code" docs:
/// https://capacitorjs.com/docs/plugins/ios#export-to-capacitor
///
/// `Main.storyboard`'s view controller custom class is set to this subclass instead of
/// `CAPBridgeViewController` directly, and `SceneDelegate.swift` instantiates it explicitly
/// for the same reason (it builds the root view controller in code rather than by loading it
/// from the storyboard).
///
/// UNVERIFIED — written without Xcode/a Mac available in this environment.
class BridgeViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(BleAdvertiserPlugin())
    }
}
