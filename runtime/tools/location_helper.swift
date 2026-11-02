import CoreLocation
import Darwin
import Foundation

final class LocationDelegate: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var finished = false

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func start() {
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorized, .authorizedAlways, .authorizedWhenInUse:
            manager.startUpdatingLocation()
        case .denied, .restricted:
            finish(error: "Location permission was denied or restricted.")
        case .notDetermined:
            break
        @unknown default:
            finish(error: "Unknown location authorization status.")
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        let payload: [String: Any] = [
            "source": "macos_core_location",
            "latitude": location.coordinate.latitude,
            "longitude": location.coordinate.longitude,
            "accuracy_meters": location.horizontalAccuracy,
            "timestamp": ISO8601DateFormatter().string(from: location.timestamp),
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: payload)
            print(String(decoding: data, as: UTF8.self))
            finish()
        } catch {
            finish(error: "Could not encode location response.")
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(error: error.localizedDescription)
    }

    func timeout() {
        let status: String
        switch manager.authorizationStatus {
        case .notDetermined: status = "notDetermined"
        case .restricted: status = "restricted"
        case .denied: status = "denied"
        case .authorized, .authorizedAlways, .authorizedWhenInUse: status = "authorized"
        @unknown default: status = "unknown"
        }
        finish(error: "Timed out waiting for a location (authorization: \(status)).")
    }

    private func finish(error: String? = nil) {
        guard !finished else { return }
        finished = true
        manager.stopUpdatingLocation()
        if let error {
            let payload = ["error": error]
            if let data = try? JSONSerialization.data(withJSONObject: payload) {
                print(String(decoding: data, as: UTF8.self))
            }
            exit(1)
        }
        CFRunLoopStop(CFRunLoopGetMain())
    }
}

let delegate = LocationDelegate()
delegate.start()
DispatchQueue.main.asyncAfter(deadline: .now() + 60) {
    delegate.timeout()
}
RunLoop.main.run()
