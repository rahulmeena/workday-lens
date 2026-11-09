import AppKit
import ApplicationServices
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

private let captureSchema = "workday_lens_capture_event.v1"
private let defaultBackendURL = URL(string: "http://127.0.0.1:8000/api/v1/capture/events/batch")!
private let hoverThrottleSeconds: TimeInterval = 0.35
private let pollSeconds: TimeInterval = 1.5
private let heartbeatSeconds: TimeInterval = 20
private let scrollStopDelaySeconds: TimeInterval = 0.65
private let redactedTextMarker = "[redacted]"

private let sensitiveTextTokens = [
    "password",
    "passcode",
    "otp",
    "one time",
    "one-time",
    "verification code",
    "security code",
    "secret",
    "token",
    "api key",
    "private key",
    "mnemonic",
    "seed phrase",
    "recovery phrase",
    "credit card",
    "card number",
    "cvv",
    "ssn",
    "social security"
]

private let sensitiveBundleFragments = [
    "keychain",
    "1password",
    "onepassword",
    "lastpass",
    "bitwarden",
    "dashlane",
    "keeper",
    "nordpass"
]

private func currentThermalStateSnapshot() -> (state: String, rank: Int) {
    switch ProcessInfo.processInfo.thermalState {
    case .nominal:
        return ("nominal", 0)
    case .fair:
        return ("fair", 1)
    case .serious:
        return ("serious", 2)
    case .critical:
        return ("critical", 3)
    @unknown default:
        return ("unknown", -1)
    }
}

struct CaptureBounds: Codable, Equatable {
    var x: Double
    var y: Double
    var width: Double
    var height: Double
}

struct CaptureAncestor: Codable, Equatable {
    var role: String?
    var subrole: String?
    var name: String?
    var description: String?
}

struct CaptureScreenshotMetadata: Codable, Equatable {
    var localPath: String
    var reason: String
    var capturedAt: Date
    var width: Int?
    var height: Int?

    enum CodingKeys: String, CodingKey {
        case localPath = "local_path"
        case reason
        case capturedAt = "captured_at"
        case width
        case height
    }
}

struct CaptureEvent: Codable, Equatable {
    var schema = captureSchema
    var eventId: String
    var capturedAt: Date
    var sourcePlatform = "macos"
    var tag: String
    var appName: String?
    var bundleId: String?
    var processId: Int?
    var windowTitle: String?
    var windowId: String?
    var windowBounds: CaptureBounds?
    var role: String?
    var subrole: String?
    var name: String?
    var value: String?
    var description: String?
    var selectedText: String?
    var states: [String]
    var keyboardShortcut: String?
    var elementBounds: CaptureBounds?
    var ancestors: [CaptureAncestor]
    var x: Int?
    var y: Int?
    var button: String?
    var state: String?
    var scrollAxis: String?
    var scrollDirection: String?
    var commandKeyName: String?
    var screenshot: CaptureScreenshotMetadata?
    var extra: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case schema
        case eventId = "event_id"
        case capturedAt = "captured_at"
        case sourcePlatform = "source_platform"
        case tag
        case appName = "app_name"
        case bundleId = "bundle_id"
        case processId = "process_id"
        case windowTitle = "window_title"
        case windowId = "window_id"
        case windowBounds = "window_bounds"
        case role
        case subrole
        case name
        case value
        case description
        case selectedText = "selected_text"
        case states
        case keyboardShortcut = "keyboard_shortcut"
        case elementBounds = "element_bounds"
        case ancestors
        case x
        case y
        case button
        case state
        case scrollAxis = "scroll_axis"
        case scrollDirection = "scroll_direction"
        case commandKeyName = "command_key_name"
        case screenshot
        case extra
    }

    init(
        tag: String,
        snapshot: AccessibilitySnapshot,
        point: CGPoint? = nil,
        button: String? = nil,
        state: String? = nil,
        scrollAxis: String? = nil,
        scrollDirection: String? = nil,
        commandKeyName: String? = nil,
        keyboardShortcut: String? = nil,
        screenshot: CaptureScreenshotMetadata? = nil,
        extra: [String: JSONValue] = [:]
    ) {
        self.eventId = UUID().uuidString
        self.capturedAt = Date()
        self.tag = tag
        self.appName = clipped(snapshot.appName, maxLength: 256)
        self.bundleId = clipped(snapshot.bundleId, maxLength: 512)
        self.processId = snapshot.processId
        self.windowTitle = clipped(snapshot.windowTitle, maxLength: 1024)
        self.windowId = clipped(snapshot.windowId, maxLength: 256)
        self.windowBounds = snapshot.windowBounds
        self.role = clipped(snapshot.role, maxLength: 128)
        self.subrole = clipped(snapshot.subrole, maxLength: 128)
        self.name = clipped(snapshot.name, maxLength: 2048)
        self.value = clipped(snapshot.value, maxLength: 4096)
        self.description = clipped(snapshot.description, maxLength: 2048)
        self.selectedText = clipped(snapshot.selectedText, maxLength: 4096)
        self.states = snapshot.states.map { clipped($0, maxLength: 128) ?? "" }.filter { !$0.isEmpty }
        self.keyboardShortcut = clipped(keyboardShortcut ?? snapshot.keyboardShortcut, maxLength: 128)
        self.elementBounds = snapshot.elementBounds
        self.ancestors = snapshot.ancestors.map { ancestor in
            CaptureAncestor(
                role: clipped(ancestor.role, maxLength: 128),
                subrole: clipped(ancestor.subrole, maxLength: 128),
                name: clipped(ancestor.name, maxLength: 512),
                description: clipped(ancestor.description, maxLength: 512)
            )
        }
        if let point {
            self.x = Int(point.x.rounded())
            self.y = Int(point.y.rounded())
        }
        self.button = button
        self.state = state
        self.scrollAxis = scrollAxis
        self.scrollDirection = scrollDirection
        self.commandKeyName = commandKeyName
        self.screenshot = screenshot
        self.extra = extra
    }
}

private func clipped(_ value: String?, maxLength: Int) -> String? {
    guard let value else { return nil }
    if value.count <= maxLength {
        return value
    }
    return String(value.prefix(maxLength))
}

enum JSONValue: Codable, Equatable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else {
            self = .string(try container.decode(String.self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .int(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        }
    }
}

struct CaptureBatch: Codable {
    var events: [CaptureEvent]
}

struct AccessibilitySnapshot: Equatable {
    var appName: String?
    var bundleId: String?
    var processId: Int?
    var windowTitle: String?
    var windowId: String?
    var windowBounds: CaptureBounds?
    var role: String?
    var subrole: String?
    var name: String?
    var value: String?
    var description: String?
    var selectedText: String?
    var states: [String] = []
    var keyboardShortcut: String?
    var elementBounds: CaptureBounds?
    var ancestors: [CaptureAncestor] = []

    static var empty: AccessibilitySnapshot {
        AccessibilitySnapshot()
    }
}

struct RedactedAccessibilitySnapshot {
    var snapshot: AccessibilitySnapshot
    var redacted: Bool
    var reason: String?
}

struct PermissionState: Equatable {
    var accessibility: Bool
    var inputMonitoring: Bool
    var screenRecording: Bool?

    var summary: String {
        let screen = screenRecording.map { $0 ? "Screen OK" : "Screen Needed" } ?? "Screen Off"
        return [
            accessibility ? "AX OK" : "AX Needed",
            inputMonitoring ? "Input OK" : "Input Needed",
            screen
        ].joined(separator: " | ")
    }
}

final class CaptureController {
    var onStatusChanged: (() -> Void)?

    private let buffer: EventBuffer
    private let screenshotStore: ScreenshotStore
    private let accessibilityWatcher: AccessibilityWatcher
    private let inputWatcher: InputWatcher
    private let gestureWatcher: GestureWatcher
    private let systemStateWatcher: SystemStateWatcher
    private var heartbeatTimer: Timer?

    private(set) var paused = false {
        didSet {
            inputWatcher.setEnabled(!paused)
            gestureWatcher.setEnabled(!paused)
            systemStateWatcher.setEnabled(!paused)
            onStatusChanged?()
        }
    }

    var screenshotsEnabled: Bool {
        didSet {
            UserDefaults.standard.set(screenshotsEnabled, forKey: "screenshotsEnabled")
            onStatusChanged?()
        }
    }

    init(buffer: EventBuffer, screenshotStore: ScreenshotStore) {
        self.buffer = buffer
        self.screenshotStore = screenshotStore
        self.screenshotsEnabled = UserDefaults.standard.bool(forKey: "screenshotsEnabled")
        self.accessibilityWatcher = AccessibilityWatcher()
        self.inputWatcher = InputWatcher()
        self.gestureWatcher = GestureWatcher()
        self.systemStateWatcher = SystemStateWatcher()
        self.accessibilityWatcher.emit = { [weak self] event in
            guard self?.paused == false else { return }
            self?.buffer.enqueue(event)
        }
        self.inputWatcher.snapshotProvider = { [weak accessibilityWatcher] point in
            accessibilityWatcher?.snapshot(at: point) ?? AccessibilitySnapshot.empty
        }
        self.inputWatcher.screenshotProvider = { [weak screenshotStore] reason in
            screenshotStore?.capture(reason: reason)
        }
        self.inputWatcher.shouldCaptureScreenshots = { [weak self] in
            self?.screenshotsEnabled == true
        }
        self.inputWatcher.emit = { [weak self] event in
            guard self?.paused == false else { return }
            self?.buffer.enqueue(event)
        }
        self.gestureWatcher.snapshotProvider = { [weak accessibilityWatcher] in
            accessibilityWatcher?.currentSnapshot() ?? AccessibilitySnapshot.empty
        }
        self.gestureWatcher.emit = { [weak self] event in
            guard self?.paused == false else { return }
            self?.buffer.enqueue(event)
        }
        self.systemStateWatcher.snapshotProvider = { [weak accessibilityWatcher] in
            accessibilityWatcher?.currentSnapshot() ?? AccessibilitySnapshot.empty
        }
        self.systemStateWatcher.emit = { [weak self] event in
            guard self?.paused == false else { return }
            self?.buffer.enqueue(event)
        }
    }

    func start() {
        accessibilityWatcher.start()
        inputWatcher.start()
        gestureWatcher.start()
        systemStateWatcher.start()
        heartbeatTimer = Timer.scheduledTimer(withTimeInterval: heartbeatSeconds, repeats: true) { [weak self] _ in
            self?.emitHeartbeat()
        }
        emitHeartbeat()
    }

    func stop() {
        heartbeatTimer?.invalidate()
        heartbeatTimer = nil
        inputWatcher.stop()
        gestureWatcher.stop()
        systemStateWatcher.stop()
        accessibilityWatcher.stop()
    }

    func pause() {
        paused = true
    }

    func resume() {
        paused = false
        emitHeartbeat()
    }

    func permissions() -> PermissionState {
        PermissionState(
            accessibility: AXIsProcessTrusted(),
            inputMonitoring: CGPreflightListenEventAccess(),
            screenRecording: screenshotsEnabled ? CGPreflightScreenCaptureAccess() : nil
        )
    }

    func requestPermissions() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        _ = CGRequestListenEventAccess()
        if screenshotsEnabled {
            _ = CGRequestScreenCaptureAccess()
        }
        onStatusChanged?()
    }

    func requestMissingPermissionsIfNeeded() {
        let state = permissions()
        let screenMissing = state.screenRecording == false
        if !state.accessibility || !state.inputMonitoring || screenMissing {
            requestPermissions()
        }
    }

    private func emitHeartbeat() {
        guard !paused else { return }
        let snapshot = accessibilityWatcher.currentSnapshot()
        let thermal = currentThermalStateSnapshot()
        let event = CaptureEvent(
            tag: "heartbeat",
            snapshot: snapshot,
            extra: [
                "capture_health": .string("running"),
                "screenshots_enabled": .bool(screenshotsEnabled),
                "thermal_source": .string("process_info"),
                "thermal_state": .string(thermal.state),
                "thermal_state_rank": .int(thermal.rank)
            ]
        )
        buffer.enqueue(event)
    }
}

final class EventBuffer {
    private let queue = DispatchQueue(label: "com.workdaylens.capture.buffer")
    private let fileURL: URL
    private let backendURL: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private var flushScheduled = false
    private var flushing = false
    private let batchSize = 50

    var onBackendHealthChanged: ((Bool) -> Void)?
    private(set) var backendHealthy = false {
        didSet {
            if oldValue != backendHealthy {
                DispatchQueue.main.async { [backendHealthy, onBackendHealthChanged] in
                    onBackendHealthChanged?(backendHealthy)
                }
            }
        }
    }

    init(appSupportDirectory: URL, backendURL: URL = defaultBackendURL) {
        self.fileURL = appSupportDirectory.appendingPathComponent("CaptureBuffer/pending_events.jsonl")
        self.backendURL = backendURL
        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()
        self.encoder.dateEncodingStrategy = .iso8601WithFractionalSeconds
        self.decoder.dateDecodingStrategy = .iso8601WithFractionalSeconds
        try? FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    }

    func enqueue(_ event: CaptureEvent) {
        queue.async {
            self.append(event)
            self.scheduleFlush(delay: 0.25)
        }
    }

    func flushNow() {
        queue.async {
            self.flush()
        }
    }

    private func append(_ event: CaptureEvent) {
        guard let data = try? encoder.encode(event) else { return }
        if !FileManager.default.fileExists(atPath: fileURL.path) {
            FileManager.default.createFile(atPath: fileURL.path, contents: nil)
        }
        guard let handle = try? FileHandle(forWritingTo: fileURL) else { return }
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: data)
        try? handle.write(contentsOf: Data([0x0A]))
    }

    private func scheduleFlush(delay: TimeInterval) {
        guard !flushScheduled else { return }
        flushScheduled = true
        queue.asyncAfter(deadline: .now() + delay) {
            self.flushScheduled = false
            self.flush()
        }
    }

    private func flush() {
        guard !flushing else { return }
        flushing = true
        let events = loadPendingEvents()
        guard !events.isEmpty else {
            flushing = false
            return
        }
        let batch = Array(events.prefix(batchSize))
        post(batch) { [weak self] success in
            guard let self else { return }
            self.queue.async {
                self.backendHealthy = success
                if success {
                    self.rewrite(events: Array(events.dropFirst(batch.count)))
                    self.flushing = false
                    if events.count > batch.count {
                        self.scheduleFlush(delay: 0.1)
                    }
                } else {
                    self.flushing = false
                    self.scheduleFlush(delay: 5.0)
                }
            }
        }
    }

    private func loadPendingEvents() -> [CaptureEvent] {
        guard let data = try? Data(contentsOf: fileURL), !data.isEmpty else { return [] }
        let lines = String(decoding: data, as: UTF8.self).split(separator: "\n")
        return lines.compactMap { line in
            guard let lineData = line.data(using: .utf8) else { return nil }
            return try? decoder.decode(CaptureEvent.self, from: lineData)
        }
    }

    private func rewrite(events: [CaptureEvent]) {
        let payload = events.compactMap { try? encoder.encode($0) }
        let data = payload.reduce(into: Data()) { result, item in
            result.append(item)
            result.append(0x0A)
        }
        try? data.write(to: fileURL, options: .atomic)
    }

    private func post(_ events: [CaptureEvent], completion: @escaping (Bool) -> Void) {
        guard let body = try? encoder.encode(CaptureBatch(events: events)) else {
            completion(false)
            return
        }
        var request = URLRequest(url: backendURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        URLSession.shared.dataTask(with: request) { _, response, error in
            if error != nil {
                completion(false)
                return
            }
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            completion((200..<300).contains(code))
        }.resume()
    }
}

final class AccessibilityWatcher {
    var emit: ((CaptureEvent) -> Void)?

    private var observer: AXObserver?
    private var currentApplication: NSRunningApplication?
    private var lastSnapshot = AccessibilitySnapshot.empty
    private var lastFocusSignature = ""
    private var lastTextSignature = ""
    private var lastTextSnapshot = AccessibilitySnapshot.empty
    private var lastEmittedEventSignatures: [String: String] = [:]
    private var pollTimer: Timer?

    func start() {
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(frontmostApplicationChanged(_:)),
            name: NSWorkspace.didActivateApplicationNotification,
            object: nil
        )
        installObserver(for: NSWorkspace.shared.frontmostApplication)
        pollTimer = Timer.scheduledTimer(withTimeInterval: pollSeconds, repeats: true) { [weak self] _ in
            self?.pollFocusedElement()
        }
        pollFocusedElement()
    }

    func stop() {
        NSWorkspace.shared.notificationCenter.removeObserver(self)
        pollTimer?.invalidate()
        pollTimer = nil
        if let observer {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .defaultMode)
        }
        observer = nil
    }

    func currentSnapshot() -> AccessibilitySnapshot {
        let redacted = redactedSnapshot(snapshotForFocusedElement())
        lastSnapshot = redacted.snapshot
        return redacted.snapshot
    }

    func snapshot(at point: CGPoint) -> AccessibilitySnapshot {
        var element: AXUIElement?
        let systemWide = AXUIElementCreateSystemWide()
        let result = AXUIElementCopyElementAtPosition(systemWide, Float(point.x), Float(point.y), &element)
        if result == .success, let element {
            return redactedSnapshot(snapshot(for: element, fallbackApp: focusedRunningApplication() ?? NSWorkspace.shared.frontmostApplication)).snapshot
        }
        return currentSnapshot()
    }

    @objc private func frontmostApplicationChanged(_ notification: Notification) {
        let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
        installObserver(for: app)
        let redacted = redactedSnapshot(snapshotForFocusedElement())
        lastSnapshot = redacted.snapshot
        lastFocusSignature = focusSignature(for: redacted.snapshot)
        lastTextSignature = textSignature(for: redacted.snapshot)
        lastTextSnapshot = redacted.snapshot
        emitAccessibilityEvent(tag: "foreground", redacted: redacted, extra: redactionExtra(redacted))
        emitUITextIfAvailable(redacted: redacted, source: primaryTextSource(for: redacted.snapshot))
    }

    private func installObserver(for app: NSRunningApplication?) {
        currentApplication = app
        if let observer {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .defaultMode)
        }
        observer = nil
        guard AXIsProcessTrusted(), let app else { return }
        var newObserver: AXObserver?
        let result = AXObserverCreate(app.processIdentifier, accessibilityObserverCallback, &newObserver)
        guard result == .success, let newObserver else { return }
        observer = newObserver
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        let refcon = Unmanaged.passUnretained(self).toOpaque()
        let notifications: [String] = [
            kAXFocusedWindowChangedNotification,
            kAXFocusedUIElementChangedNotification,
            kAXValueChangedNotification,
            "AXTitleChanged",
            "AXSelectedTextChanged"
        ]
        for notification in notifications {
            AXObserverAddNotification(newObserver, appElement, notification as CFString, refcon)
        }
        CFRunLoopAddSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(newObserver), .defaultMode)
    }

    fileprivate func handleAXNotification(element: AXUIElement, notification: CFString) {
        let redacted = redactedSnapshot(snapshot(for: element, fallbackApp: currentApplication))
        let snapshot = redacted.snapshot
        lastSnapshot = snapshot
        let name = notification as String
        let tag: String
        var source: String?
        switch name {
        case kAXFocusedWindowChangedNotification:
            tag = "foreground"
        case kAXFocusedUIElementChangedNotification:
            tag = "focus_entered"
        case kAXValueChangedNotification:
            tag = "value_change"
            source = "value"
        case "AXTitleChanged":
            tag = "name_change"
            source = "name"
        case "AXSelectedTextChanged":
            tag = "caret"
            source = "selected_text"
        default:
            tag = "focus"
        }
        if tag == "foreground" || tag == "focus_entered" || tag == "focus" {
            lastFocusSignature = focusSignature(for: snapshot)
            lastTextSignature = textSignature(for: snapshot)
            lastTextSnapshot = snapshot
            emitAccessibilityEvent(tag: tag, redacted: redacted, extra: redactionExtra(redacted))
            emitUITextIfAvailable(redacted: redacted, source: primaryTextSource(for: snapshot))
            return
        }
        lastTextSignature = textSignature(for: snapshot)
        lastTextSnapshot = snapshot
        emitAccessibilityEvent(tag: tag, redacted: redacted, extra: textEventExtra(redacted: redacted, source: source))
    }

    private func pollFocusedElement() {
        let redacted = redactedSnapshot(snapshotForFocusedElement())
        let snapshot = redacted.snapshot
        lastSnapshot = snapshot
        let currentFocusSignature = focusSignature(for: snapshot)
        let currentTextSignature = textSignature(for: snapshot)
        if currentFocusSignature != lastFocusSignature {
            lastFocusSignature = currentFocusSignature
            lastTextSignature = currentTextSignature
            lastTextSnapshot = snapshot
            emitAccessibilityEvent(tag: "focus", redacted: redacted, extra: redactionExtra(redacted))
            emitUITextIfAvailable(redacted: redacted, source: primaryTextSource(for: snapshot))
            return
        }
        if currentTextSignature != lastTextSignature {
            let source = changedTextSource(previous: lastTextSnapshot, current: snapshot) ?? primaryTextSource(for: snapshot)
            let tag = textChangeTag(for: source)
            lastTextSignature = currentTextSignature
            lastTextSnapshot = snapshot
            emitAccessibilityEvent(tag: tag, redacted: redacted, extra: textEventExtra(redacted: redacted, source: source))
        }
    }

    private func emitUITextIfAvailable(redacted: RedactedAccessibilitySnapshot, source: String?) {
        guard let source else { return }
        emitAccessibilityEvent(tag: "ui_text", redacted: redacted, extra: textEventExtra(redacted: redacted, source: source))
    }

    private func emitAccessibilityEvent(tag: String, redacted: RedactedAccessibilitySnapshot, extra: [String: JSONValue] = [:]) {
        let snapshot = redacted.snapshot
        let key = [
            tag,
            snapshot.bundleId ?? "",
            snapshot.windowId ?? snapshot.windowTitle ?? "",
            snapshot.role ?? "",
            snapshot.subrole ?? "",
            boundsSignature(snapshot.elementBounds),
            extraString(extra, key: "text_source")
        ].joined(separator: "|")
        let signature = [
            snapshot.name ?? "",
            snapshot.value ?? "",
            snapshot.description ?? "",
            snapshot.selectedText ?? "",
            snapshot.states.joined(separator: ","),
            extraString(extra, key: "redaction_reason")
        ].joined(separator: "|")
        if lastEmittedEventSignatures[key] == signature {
            return
        }
        lastEmittedEventSignatures[key] = signature
        emit?(CaptureEvent(tag: tag, snapshot: snapshot, extra: extra))
    }

    private func extraString(_ extra: [String: JSONValue], key: String) -> String {
        guard let value = extra[key] else { return "" }
        switch value {
        case .string(let text):
            return text
        case .int(let number):
            return "\(number)"
        case .double(let number):
            return "\(number)"
        case .bool(let bool):
            return bool ? "true" : "false"
        }
    }

    private func focusSignature(for snapshot: AccessibilitySnapshot) -> String {
        [
            snapshot.bundleId ?? "",
            snapshot.windowTitle ?? "",
            snapshot.windowId ?? "",
            snapshot.role ?? "",
            snapshot.subrole ?? "",
            snapshot.name ?? "",
            boundsSignature(snapshot.elementBounds),
            boundsSignature(snapshot.windowBounds)
        ].joined(separator: "|")
    }

    private func textSignature(for snapshot: AccessibilitySnapshot) -> String {
        [
            snapshot.value ?? "",
            snapshot.selectedText ?? "",
            snapshot.name ?? "",
            snapshot.description ?? ""
        ].joined(separator: "|")
    }

    private func boundsSignature(_ bounds: CaptureBounds?) -> String {
        guard let bounds else { return "" }
        return "\(Int(bounds.x.rounded())),\(Int(bounds.y.rounded())),\(Int(bounds.width.rounded()))x\(Int(bounds.height.rounded()))"
    }

    private func primaryTextSource(for snapshot: AccessibilitySnapshot) -> String? {
        if hasText(snapshot.value) {
            return "value"
        }
        if hasText(snapshot.selectedText) {
            return "selected_text"
        }
        if isTextLike(snapshot) {
            if hasText(snapshot.name) {
                return "name"
            }
            if hasText(snapshot.description) {
                return "description"
            }
        }
        return nil
    }

    private func changedTextSource(previous: AccessibilitySnapshot, current: AccessibilitySnapshot) -> String? {
        if previous.value != current.value {
            return "value"
        }
        if previous.selectedText != current.selectedText {
            return "selected_text"
        }
        if previous.name != current.name {
            return "name"
        }
        if previous.description != current.description {
            return "description"
        }
        return nil
    }

    private func textChangeTag(for source: String?) -> String {
        switch source {
        case "selected_text":
            return "caret"
        case "name":
            return "name_change"
        case "description":
            return "description_change"
        default:
            return "value_change"
        }
    }

    private func textEventExtra(redacted: RedactedAccessibilitySnapshot, source: String?) -> [String: JSONValue] {
        var extra = redactionExtra(redacted)
        if let source {
            extra["text_source"] = .string(source)
            if !redacted.redacted, let text = textValue(source: source, snapshot: redacted.snapshot) {
                extra["text_length"] = .int(text.count)
            }
        }
        return extra
    }

    private func redactionExtra(_ redacted: RedactedAccessibilitySnapshot) -> [String: JSONValue] {
        guard redacted.redacted else { return [:] }
        var extra: [String: JSONValue] = ["redacted": .bool(true)]
        if let reason = redacted.reason {
            extra["redaction_reason"] = .string(reason)
        }
        return extra
    }

    private func textValue(source: String, snapshot: AccessibilitySnapshot) -> String? {
        switch source {
        case "value":
            return snapshot.value
        case "selected_text":
            return snapshot.selectedText
        case "name":
            return snapshot.name
        case "description":
            return snapshot.description
        default:
            return nil
        }
    }

    private func hasText(_ value: String?) -> Bool {
        guard let value else { return false }
        return !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func isTextLike(_ snapshot: AccessibilitySnapshot) -> Bool {
        let context = [snapshot.role, snapshot.subrole].compactMap { $0 }.joined(separator: " ")
        return containsAny(context, needles: ["text", "textfield", "textarea", "statictext", "combobox", "search"])
    }

    private func redactedSnapshot(_ snapshot: AccessibilitySnapshot) -> RedactedAccessibilitySnapshot {
        guard let reason = redactionReason(for: snapshot) else {
            return RedactedAccessibilitySnapshot(snapshot: snapshot, redacted: false, reason: nil)
        }
        var copy = snapshot
        var didRedact = false
        if copy.value != nil {
            copy.value = redactedTextMarker
            didRedact = true
        }
        if copy.selectedText != nil {
            copy.selectedText = redactedTextMarker
            didRedact = true
        }
        return RedactedAccessibilitySnapshot(snapshot: copy, redacted: didRedact, reason: didRedact ? reason : nil)
    }

    private func redactionReason(for snapshot: AccessibilitySnapshot) -> String? {
        let roleContext = [snapshot.role, snapshot.subrole].compactMap { $0 }.joined(separator: " ")
        if containsAny(roleContext, needles: ["secure", "password"]) {
            return "secure_text_field"
        }
        if let bundleId = snapshot.bundleId, containsAny(bundleId, needles: sensitiveBundleFragments) {
            return "sensitive_app"
        }
        let labelContext = (
            [
                snapshot.role,
                snapshot.subrole,
                snapshot.name,
                snapshot.description,
                snapshot.windowTitle
            ]
            + snapshot.ancestors.flatMap { [$0.role, $0.subrole, $0.name, $0.description] }
        )
        .compactMap { $0 }
        .joined(separator: " ")
        if containsAny(labelContext, needles: sensitiveTextTokens) {
            return "sensitive_field_context"
        }
        let textContext = [snapshot.value, snapshot.selectedText].compactMap { $0 }.joined(separator: " ")
        if containsAny(textContext, needles: sensitiveTextTokens) {
            return "sensitive_text_content"
        }
        return nil
    }

    private func snapshotForFocusedElement() -> AccessibilitySnapshot {
        let app = focusedRunningApplication() ?? NSWorkspace.shared.frontmostApplication
        guard AXIsProcessTrusted(), let app else {
            return baseSnapshot(app: app)
        }
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        if let focusedElement = copyElementAttribute(appElement, kAXFocusedUIElementAttribute) {
            return snapshot(for: focusedElement, fallbackApp: app)
        }
        return snapshot(for: appElement, fallbackApp: app)
    }

    private func focusedRunningApplication() -> NSRunningApplication? {
        guard AXIsProcessTrusted() else { return nil }
        let systemWide = AXUIElementCreateSystemWide()
        guard let focusedApp = copyElementAttribute(systemWide, kAXFocusedApplicationAttribute) else { return nil }
        return runningApplication(for: focusedApp)
    }

    private func snapshot(for element: AXUIElement, fallbackApp: NSRunningApplication?) -> AccessibilitySnapshot {
        var snapshot = baseSnapshot(app: runningApplication(for: element) ?? fallbackApp)
        snapshot.role = copyStringAttribute(element, kAXRoleAttribute)
        snapshot.subrole = copyStringAttribute(element, kAXSubroleAttribute)
        snapshot.name = copyStringAttribute(element, kAXTitleAttribute) ?? copyStringAttribute(element, kAXDescriptionAttribute)
        snapshot.value = copyStringAttribute(element, kAXValueAttribute)
        snapshot.description = copyStringAttribute(element, kAXDescriptionAttribute)
        snapshot.selectedText = copyStringAttribute(element, kAXSelectedTextAttribute)
        snapshot.keyboardShortcut = copyStringAttribute(element, "AXMenuItemCmdChar")
        snapshot.elementBounds = elementBounds(element)
        snapshot.states = elementStates(element)
        snapshot.ancestors = ancestors(for: element)
        if let window = copyElementAttribute(element, kAXWindowAttribute) ?? copyElementAttribute(AXUIElementCreateApplication(pid_t(snapshot.processId ?? 0)), kAXFocusedWindowAttribute) {
            snapshot.windowTitle = copyStringAttribute(window, kAXTitleAttribute) ?? snapshot.windowTitle
            snapshot.windowBounds = elementBounds(window)
            snapshot.windowId = copyStringAttribute(window, kAXIdentifierAttribute) ?? snapshot.windowTitle
        }
        return snapshot
    }

    private func baseSnapshot(app: NSRunningApplication?) -> AccessibilitySnapshot {
        AccessibilitySnapshot(
            appName: app?.localizedName,
            bundleId: app?.bundleIdentifier,
            processId: app.map { Int($0.processIdentifier) },
            windowTitle: nil,
            windowId: nil,
            windowBounds: nil,
            role: nil,
            subrole: nil,
            name: nil,
            value: nil,
            description: nil,
            selectedText: nil,
            states: [],
            keyboardShortcut: nil,
            elementBounds: nil,
            ancestors: []
        )
    }

    private func runningApplication(for element: AXUIElement) -> NSRunningApplication? {
        var pid: pid_t = 0
        guard AXUIElementGetPid(element, &pid) == .success else { return nil }
        return NSRunningApplication(processIdentifier: pid)
    }

    private func ancestors(for element: AXUIElement) -> [CaptureAncestor] {
        var result: [CaptureAncestor] = []
        var cursor: AXUIElement? = element
        for _ in 0..<6 {
            guard let parent = cursor.flatMap({ copyElementAttribute($0, kAXParentAttribute) }) else { break }
            result.append(
                CaptureAncestor(
                    role: copyStringAttribute(parent, kAXRoleAttribute),
                    subrole: copyStringAttribute(parent, kAXSubroleAttribute),
                    name: copyStringAttribute(parent, kAXTitleAttribute),
                    description: copyStringAttribute(parent, kAXDescriptionAttribute)
                )
            )
            cursor = parent
        }
        return result
    }

    private func elementStates(_ element: AXUIElement) -> [String] {
        var states: [String] = []
        let boolAttributes: [(String, String)] = [
            (kAXFocusedAttribute, "focused"),
            (kAXSelectedAttribute, "selected"),
            (kAXEnabledAttribute, "enabled"),
            ("AXExpanded", "expanded")
        ]
        for (attribute, label) in boolAttributes {
            if copyBoolAttribute(element, attribute) == true {
                states.append(label)
            }
        }
        return states
    }

    private func elementBounds(_ element: AXUIElement) -> CaptureBounds? {
        guard
            let pointRaw = copyRawAttribute(element, kAXPositionAttribute),
            let sizeRaw = copyRawAttribute(element, kAXSizeAttribute)
        else {
            return nil
        }
        let pointValue = pointRaw as! AXValue
        let sizeValue = sizeRaw as! AXValue
        var point = CGPoint.zero
        var size = CGSize.zero
        guard AXValueGetValue(pointValue, .cgPoint, &point), AXValueGetValue(sizeValue, .cgSize, &size) else {
            return nil
        }
        return CaptureBounds(x: point.x, y: point.y, width: size.width, height: size.height)
    }
}

private let accessibilityObserverCallback: AXObserverCallback = { _, element, notification, refcon in
    guard let refcon else { return }
    let watcher = Unmanaged<AccessibilityWatcher>.fromOpaque(refcon).takeUnretainedValue()
    DispatchQueue.main.async {
        watcher.handleAXNotification(element: element, notification: notification)
    }
}

final class InputWatcher {
    var emit: ((CaptureEvent) -> Void)?
    var snapshotProvider: ((CGPoint) -> AccessibilitySnapshot)?
    var screenshotProvider: ((String) -> CaptureScreenshotMetadata?)?
    var shouldCaptureScreenshots: (() -> Bool)?

    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var lastHoverAt = Date.distantPast
    private var lastHoverSignature = ""
    private var scrollStopWorkItem: DispatchWorkItem?

    func start() {
        guard CGPreflightListenEventAccess() else { return }
        let mask =
            (1 << CGEventType.leftMouseDown.rawValue) |
            (1 << CGEventType.leftMouseUp.rawValue) |
            (1 << CGEventType.rightMouseDown.rawValue) |
            (1 << CGEventType.rightMouseUp.rawValue) |
            (1 << CGEventType.otherMouseDown.rawValue) |
            (1 << CGEventType.otherMouseUp.rawValue) |
            (1 << CGEventType.scrollWheel.rawValue) |
            (1 << CGEventType.mouseMoved.rawValue) |
            (1 << CGEventType.leftMouseDragged.rawValue) |
            (1 << CGEventType.rightMouseDragged.rawValue) |
            (1 << CGEventType.keyDown.rawValue)
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: CGEventMask(mask),
            callback: eventTapCallback,
            userInfo: Unmanaged.passUnretained(self).toOpaque()
        ) else {
            return
        }
        eventTap = tap
        runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        if let runLoopSource {
            CFRunLoopAddSource(CFRunLoopGetMain(), runLoopSource, .commonModes)
        }
        CGEvent.tapEnable(tap: tap, enable: true)
    }

    func stop() {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }
        if let runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), runLoopSource, .commonModes)
        }
        runLoopSource = nil
        eventTap = nil
    }

    func setEnabled(_ enabled: Bool) {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: enabled)
        }
    }

    fileprivate func handle(type: CGEventType, event: CGEvent) {
        let point = event.location
        switch type {
        case .mouseMoved, .leftMouseDragged, .rightMouseDragged:
            handleHover(point: point)
        case .leftMouseDown:
            emitMouseAction(point: point, button: "left", state: "down", screenshotReason: "clickDown")
        case .leftMouseUp:
            emitMouseAction(point: point, button: "left", state: "up")
        case .rightMouseDown:
            emitMouseAction(point: point, button: "right", state: "down", screenshotReason: "clickDown")
        case .rightMouseUp:
            emitMouseAction(point: point, button: "right", state: "up")
        case .otherMouseDown:
            emitMouseAction(point: point, button: "other", state: "down", screenshotReason: "clickDown")
        case .otherMouseUp:
            emitMouseAction(point: point, button: "other", state: "up")
        case .scrollWheel:
            handleScroll(event: event, point: point)
        case .keyDown:
            handleKeyDown(event: event, point: point)
        default:
            break
        }
    }

    private func handleHover(point: CGPoint) {
        let now = Date()
        guard now.timeIntervalSince(lastHoverAt) >= hoverThrottleSeconds else { return }
        lastHoverAt = now
        let snapshot = snapshotProvider?(point) ?? AccessibilitySnapshot.empty
        let signature = [
            snapshot.bundleId ?? "",
            snapshot.role ?? "",
            snapshot.name ?? "",
            snapshot.elementBounds.map { "\($0.x),\($0.y),\($0.width),\($0.height)" } ?? "",
            "\(Int(point.x))",
            "\(Int(point.y))"
        ].joined(separator: "|")
        guard signature != lastHoverSignature else { return }
        lastHoverSignature = signature
        emit?(CaptureEvent(tag: "mouse_hover", snapshot: snapshot, point: point))
    }

    private func emitMouseAction(point: CGPoint, button: String, state: String, screenshotReason: String? = nil) {
        let snapshot = snapshotProvider?(point) ?? AccessibilitySnapshot.empty
        var screenshot: CaptureScreenshotMetadata?
        if let screenshotReason, shouldCaptureScreenshots?() == true {
            screenshot = screenshotProvider?(screenshotReason)
        }
        emit?(
            CaptureEvent(
                tag: "mouse_action",
                snapshot: snapshot,
                point: point,
                button: button,
                state: state,
                screenshot: screenshot,
                extra: ["action": .string("\(button)\(state.capitalized)")]
            )
        )
    }

    private func handleScroll(event: CGEvent, point: CGPoint) {
        let deltaY = event.getIntegerValueField(.scrollWheelEventDeltaAxis1)
        let deltaX = event.getIntegerValueField(.scrollWheelEventDeltaAxis2)
        let axis: String
        let direction: String
        if abs(deltaX) > abs(deltaY) {
            axis = "horizontal"
            direction = deltaX > 0 ? "right" : "left"
        } else {
            axis = "vertical"
            direction = deltaY > 0 ? "up" : "down"
        }
        let snapshot = snapshotProvider?(point) ?? AccessibilitySnapshot.empty
        emit?(
            CaptureEvent(
                tag: "mouse_action",
                snapshot: snapshot,
                point: point,
                scrollAxis: axis,
                scrollDirection: direction,
                extra: ["action": .string("scroll\(direction.capitalized)")]
            )
        )
        scheduleScrollStop(point: point)
    }

    private func scheduleScrollStop(point: CGPoint) {
        scrollStopWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            let snapshot = self.snapshotProvider?(point) ?? AccessibilitySnapshot.empty
            let screenshot = self.shouldCaptureScreenshots?() == true ? self.screenshotProvider?("scrollStop") : nil
            self.emit?(
                CaptureEvent(
                    tag: "mouse_action",
                    snapshot: snapshot,
                    point: point,
                    state: "stop",
                    screenshot: screenshot,
                    extra: ["action": .string("scrollStop")]
                )
            )
        }
        scrollStopWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + scrollStopDelaySeconds, execute: workItem)
    }

    private func handleKeyDown(event: CGEvent, point: CGPoint) {
        if event.flags.contains(.maskCommand) {
            handleCommandKey(event: event, point: point)
            return
        }
        handleRedactedKeyboardActivity(event: event, point: point)
    }

    private func handleCommandKey(event: CGEvent, point: CGPoint) {
        let code = Int(event.getIntegerValueField(.keyboardEventKeycode))
        let keyName = keyNameForCommandKey(code: code)
        let snapshot = snapshotProvider?(point) ?? AccessibilitySnapshot.empty
        emit?(
            CaptureEvent(
                tag: "command_key",
                snapshot: snapshot,
                point: point,
                commandKeyName: keyName,
                keyboardShortcut: "Command+\(keyName.uppercased())"
            )
        )
    }

    private func handleRedactedKeyboardActivity(event: CGEvent, point: CGPoint) {
        let code = Int(event.getIntegerValueField(.keyboardEventKeycode))
        let snapshot = snapshotProvider?(point) ?? AccessibilitySnapshot.empty
        emit?(
            CaptureEvent(
                tag: "keyboard_activity",
                snapshot: snapshot,
                point: point,
                extra: [
                    "key_class": .string(keyClassForRedactedKey(code: code)),
                    "key_redacted": .bool(true),
                    "modifiers": .string(redactedModifierSummary(event.flags))
                ]
            )
        )
    }

    private func keyClassForRedactedKey(code: Int) -> String {
        let navigationKeys: Set<Int> = [115, 116, 119, 121, 123, 124, 125, 126]
        let editingKeys: Set<Int> = [36, 48, 51, 53, 76, 117]
        let functionKeys: Set<Int> = [96, 97, 98, 99, 100, 101, 103, 105, 107, 109, 111, 113, 118, 120, 122]
        if navigationKeys.contains(code) {
            return "navigation"
        }
        if editingKeys.contains(code) {
            return "editing"
        }
        if functionKeys.contains(code) {
            return "function"
        }
        return "character"
    }

    private func redactedModifierSummary(_ flags: CGEventFlags) -> String {
        var names: [String] = []
        if flags.contains(.maskShift) {
            names.append("shift")
        }
        if flags.contains(.maskAlternate) {
            names.append("option")
        }
        if flags.contains(.maskControl) {
            names.append("control")
        }
        return names.joined(separator: ",")
    }

    private func keyNameForCommandKey(code: Int) -> String {
        let names: [Int: String] = [
            0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x",
            8: "c", 9: "v", 11: "b", 12: "q", 13: "w", 14: "e", 15: "r",
            16: "y", 17: "t", 31: "o", 32: "u", 34: "i", 35: "p", 37: "l",
            38: "j", 40: "k", 45: "n", 46: "m", 49: "space", 51: "delete",
            53: "escape", 123: "left", 124: "right", 125: "down", 126: "up"
        ]
        return names[code] ?? "keycode_\(code)"
    }
}

final class GestureWatcher: NSObject {
    var emit: ((CaptureEvent) -> Void)?
    var snapshotProvider: (() -> AccessibilitySnapshot)?

    private var enabled = true
    private var monitors: [Any] = []
    private var lastEmittedAtBySignature: [String: Date] = [:]
    private var lastSpaceChangeAt = Date.distantPast
    private var lastSwipeDirection: String?
    private var lastSwipeAt = Date.distantPast

    func start() {
        let mask: NSEvent.EventTypeMask = [.swipe, .magnify, .smartMagnify, .rotate]
        if let monitor = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: { [weak self] event in
            DispatchQueue.main.async {
                self?.handle(event: event)
            }
        }) {
            monitors.append(monitor)
        }
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(activeSpaceChanged(_:)),
            name: NSWorkspace.activeSpaceDidChangeNotification,
            object: nil
        )
    }

    func stop() {
        for monitor in monitors {
            NSEvent.removeMonitor(monitor)
        }
        monitors = []
        NSWorkspace.shared.notificationCenter.removeObserver(self)
    }

    func setEnabled(_ enabled: Bool) {
        self.enabled = enabled
    }

    private func handle(event: NSEvent) {
        guard enabled else { return }
        switch event.type {
        case .swipe:
            handleSwipe(event)
        case .magnify:
            handleMagnify(event)
        case .smartMagnify:
            emitGesture(
                gestureType: "smart_zoom",
                action: "smartZoom",
                source: "nsevent_global_monitor",
                throttleKey: "smartZoom"
            )
        case .rotate:
            handleRotate(event)
        default:
            break
        }
    }

    private func handleSwipe(_ event: NSEvent) {
        let deltaX = Double(event.deltaX)
        let deltaY = Double(event.deltaY)
        guard abs(deltaX) > 0 || abs(deltaY) > 0 else { return }
        let axis: String
        let direction: String
        let magnitude: Double
        if abs(deltaX) >= abs(deltaY) {
            axis = "horizontal"
            direction = deltaX > 0 ? "right" : "left"
            magnitude = abs(deltaX)
            lastSwipeDirection = direction
            lastSwipeAt = Date()
        } else {
            axis = "vertical"
            direction = deltaY > 0 ? "up" : "down"
            magnitude = abs(deltaY)
        }
        emitGesture(
            gestureType: "swipe",
            action: "swipe\(direction.capitalized)",
            axis: axis,
            direction: direction,
            magnitude: roundedMagnitude(magnitude),
            source: "nsevent_global_monitor",
            throttleKey: "swipe:\(axis):\(direction)"
        )
    }

    private func handleMagnify(_ event: NSEvent) {
        let magnification = Double(event.magnification)
        guard abs(magnification) >= 0.01 else { return }
        let direction = magnification > 0 ? "in" : "out"
        emitGesture(
            gestureType: "zoom",
            action: magnification > 0 ? "zoomIn" : "zoomOut",
            direction: direction,
            magnitude: roundedMagnitude(abs(magnification)),
            source: "nsevent_global_monitor",
            throttleKey: "zoom:\(direction)"
        )
    }

    private func handleRotate(_ event: NSEvent) {
        let rotation = Double(event.rotation)
        guard abs(rotation) >= 1 else { return }
        let direction = rotation > 0 ? "clockwise" : "counterclockwise"
        emitGesture(
            gestureType: "rotate",
            action: rotation > 0 ? "rotateClockwise" : "rotateCounterclockwise",
            direction: direction,
            magnitude: roundedMagnitude(abs(rotation)),
            source: "nsevent_global_monitor",
            throttleKey: "rotate:\(direction)"
        )
    }

    @objc private func activeSpaceChanged(_ notification: Notification) {
        guard enabled else { return }
        let now = Date()
        guard now.timeIntervalSince(lastSpaceChangeAt) >= 0.75 else { return }
        lastSpaceChangeAt = now
        var direction: String?
        if now.timeIntervalSince(lastSwipeAt) <= 2.0 {
            direction = lastSwipeDirection
        }
        emitGesture(
            gestureType: "desktop_switch",
            action: "desktopSwitch",
            axis: direction == nil ? nil : "horizontal",
            direction: direction,
            source: "active_space_notification",
            throttleKey: "desktopSwitch:\(direction ?? "unknown")",
            minimumInterval: 0.75
        )
    }

    private func emitGesture(
        gestureType: String,
        action: String,
        axis: String? = nil,
        direction: String? = nil,
        magnitude: Double? = nil,
        source: String,
        throttleKey: String,
        minimumInterval: TimeInterval = 0.35
    ) {
        guard shouldEmit(throttleKey, minimumInterval: minimumInterval) else { return }
        var extra: [String: JSONValue] = [
            "gesture_type": .string(gestureType),
            "action": .string(action),
            "source": .string(source)
        ]
        if let axis {
            extra["axis"] = .string(axis)
        }
        if let direction {
            extra["direction"] = .string(direction)
        }
        if let magnitude {
            extra["magnitude"] = .double(magnitude)
        }
        let snapshot = snapshotProvider?() ?? AccessibilitySnapshot.empty
        emit?(CaptureEvent(tag: "gesture", snapshot: snapshot, extra: extra))
    }

    private func shouldEmit(_ signature: String, minimumInterval: TimeInterval) -> Bool {
        let now = Date()
        if let lastEmittedAt = lastEmittedAtBySignature[signature], now.timeIntervalSince(lastEmittedAt) < minimumInterval {
            return false
        }
        lastEmittedAtBySignature[signature] = now
        return true
    }

    private func roundedMagnitude(_ value: Double) -> Double {
        (value * 1000).rounded() / 1000
    }
}

final class SystemStateWatcher: NSObject {
    var emit: ((CaptureEvent) -> Void)?
    var snapshotProvider: (() -> AccessibilitySnapshot)?

    private struct Descriptor {
        var action: String
        var state: String
        var source: String
    }

    private let workspaceEventMap: [Notification.Name: Descriptor] = [
        NSWorkspace.willSleepNotification: Descriptor(action: "systemSleep", state: "sleeping", source: "workspace_notification"),
        NSWorkspace.didWakeNotification: Descriptor(action: "systemWake", state: "awake", source: "workspace_notification"),
        NSWorkspace.screensDidSleepNotification: Descriptor(action: "displaySleep", state: "display_sleep", source: "workspace_notification"),
        NSWorkspace.screensDidWakeNotification: Descriptor(action: "displayWake", state: "display_awake", source: "workspace_notification")
    ]
    private let distributedEventMap: [Notification.Name: Descriptor] = [
        Notification.Name("com.apple.screenIsLocked"): Descriptor(action: "screenLocked", state: "locked", source: "distributed_notification"),
        Notification.Name("com.apple.screenIsUnlocked"): Descriptor(action: "screenUnlocked", state: "unlocked", source: "distributed_notification"),
        Notification.Name("com.apple.screensaver.didstart"): Descriptor(action: "screensaverStarted", state: "running", source: "distributed_notification"),
        Notification.Name("com.apple.screensaver.didstop"): Descriptor(action: "screensaverStopped", state: "stopped", source: "distributed_notification")
    ]
    private var enabled = true
    private var lastEmittedAtBySignature: [String: Date] = [:]

    func start() {
        let workspaceCenter = NSWorkspace.shared.notificationCenter
        for name in workspaceEventMap.keys {
            workspaceCenter.addObserver(
                self,
                selector: #selector(handleWorkspaceNotification(_:)),
                name: name,
                object: nil
            )
        }
        let distributedCenter = DistributedNotificationCenter.default()
        for name in distributedEventMap.keys {
            distributedCenter.addObserver(
                self,
                selector: #selector(handleDistributedNotification(_:)),
                name: name,
                object: nil
            )
        }
    }

    func stop() {
        NSWorkspace.shared.notificationCenter.removeObserver(self)
        DistributedNotificationCenter.default().removeObserver(self)
    }

    func setEnabled(_ enabled: Bool) {
        self.enabled = enabled
    }

    @objc private func handleWorkspaceNotification(_ notification: Notification) {
        guard let descriptor = workspaceEventMap[notification.name] else { return }
        emitSystemState(descriptor, notificationName: notification.name.rawValue)
    }

    @objc private func handleDistributedNotification(_ notification: Notification) {
        guard let descriptor = distributedEventMap[notification.name] else { return }
        emitSystemState(descriptor, notificationName: notification.name.rawValue)
    }

    private func emitSystemState(_ descriptor: Descriptor, notificationName: String) {
        guard enabled else { return }
        let signature = "\(descriptor.action):\(descriptor.state)"
        guard shouldEmit(signature, minimumInterval: 0.75) else { return }
        let snapshot = snapshotProvider?() ?? AccessibilitySnapshot.empty
        emit?(
            CaptureEvent(
                tag: "system_state",
                snapshot: snapshot,
                extra: [
                    "action": .string(descriptor.action),
                    "state": .string(descriptor.state),
                    "source": .string(descriptor.source),
                    "notification_name": .string(notificationName)
                ]
            )
        )
    }

    private func shouldEmit(_ signature: String, minimumInterval: TimeInterval) -> Bool {
        let now = Date()
        if let lastEmittedAt = lastEmittedAtBySignature[signature], now.timeIntervalSince(lastEmittedAt) < minimumInterval {
            return false
        }
        lastEmittedAtBySignature[signature] = now
        return true
    }
}

private let eventTapCallback: CGEventTapCallBack = { _, type, event, refcon in
    guard let refcon else { return Unmanaged.passUnretained(event) }
    let watcher = Unmanaged<InputWatcher>.fromOpaque(refcon).takeUnretainedValue()
    DispatchQueue.main.async {
        watcher.handle(type: type, event: event)
    }
    return Unmanaged.passUnretained(event)
}

final class ScreenshotStore {
    private let rootDirectory: URL
    private let formatter: DateFormatter

    init(appSupportDirectory: URL) {
        self.rootDirectory = appSupportDirectory.appendingPathComponent("ScreenCaptures")
        self.formatter = DateFormatter()
        self.formatter.calendar = Calendar(identifier: .gregorian)
        self.formatter.locale = Locale(identifier: "en_US_POSIX")
        self.formatter.timeZone = .current
        self.formatter.dateFormat = "yyyy/MM/dd/HH"
    }

    func capture(reason: String) -> CaptureScreenshotMetadata? {
        guard CGPreflightScreenCaptureAccess() else { return nil }
        guard let image = CGWindowListCreateImage(.infinite, .optionOnScreenOnly, kCGNullWindowID, [.bestResolution]) else {
            return nil
        }
        let now = Date()
        let directory = rootDirectory.appendingPathComponent(formatter.string(from: now), isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let fileURL = directory.appendingPathComponent("\(UUID().uuidString).png")
        guard let destination = CGImageDestinationCreateWithURL(fileURL as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            return nil
        }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return CaptureScreenshotMetadata(
            localPath: fileURL.path,
            reason: reason,
            capturedAt: now,
            width: image.width,
            height: image.height
        )
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var controller: CaptureController!
    private var buffer: EventBuffer!
    private var backendHealthy = false
    private var menuRefreshTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        debugLog("[Menu] Helper started; pid=\(ProcessInfo.processInfo.processIdentifier)")
        let appSupport = appSupportDirectory()
        let screenshotStore = ScreenshotStore(appSupportDirectory: appSupport)
        buffer = EventBuffer(appSupportDirectory: appSupport)
        controller = CaptureController(buffer: buffer, screenshotStore: screenshotStore)
        controller.onStatusChanged = { [weak self] in self?.rebuildMenu() }
        buffer.onBackendHealthChanged = { [weak self] healthy in
            self?.backendHealthy = healthy
            self?.rebuildMenu()
        }
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "Workday Lens"
        controller.start()
        rebuildMenu()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.controller.requestMissingPermissionsIfNeeded()
            self?.rebuildMenu()
        }
        menuRefreshTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.buffer.flushNow()
            self?.rebuildMenu()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        menuRefreshTimer?.invalidate()
        controller.stop()
        buffer.flushNow()
    }

    @objc private func togglePause() {
        debugLog("[Menu] \(controller.paused ? "Resume" : "Pause") Capture action received")
        controller.paused ? controller.resume() : controller.pause()
        debugLog("[Menu] Capture is now \(controller.paused ? "paused" : "running")")
        buffer.flushNow()
        rebuildMenu()
    }

    @objc private func toggleScreenshots() {
        controller.screenshotsEnabled.toggle()
        rebuildMenu()
    }

    @objc private func requestPermissions() {
        controller.requestPermissions()
        rebuildMenu()
    }

    @objc private func openDashboard() {
        debugLog("[Menu] Open Dashboard action received")
        Task {
            let candidates = await dashboardURLCandidates()
            let url = await firstReachableDashboardURL(from: candidates) ?? candidates.first!
            await MainActor.run {
                openDashboardURL(url)
            }
        }
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func rebuildMenu() {
        guard statusItem != nil else { return }
        let menu = NSMenu()
        let permissions = controller.permissions()
        let pauseTitle = controller.paused ? "Resume Capture" : "Pause Capture"
        statusItem.button?.title = controller.paused ? "Lens Paused" : "Workday Lens"

        menu.addItem(actionItem(title: pauseTitle, action: #selector(togglePause)))
        menu.addItem(actionItem(title: "Open Dashboard", action: #selector(openDashboard)))
        menu.addItem(.separator())
        menu.addItem(disabledItem("Capture: \(controller.paused ? "Paused" : "Running")"))
        menu.addItem(disabledItem("Backend: \(backendHealthy ? "Healthy" : "Waiting")"))
        menu.addItem(disabledItem("Permissions: \(permissions.summary)"))
        menu.addItem(.separator())
        let screenshotTitle = controller.screenshotsEnabled ? "Disable Local Screenshots" : "Enable Local Screenshots"
        menu.addItem(actionItem(title: screenshotTitle, action: #selector(toggleScreenshots)))
        menu.addItem(actionItem(title: "Request Permissions", action: #selector(requestPermissions)))
        menu.addItem(.separator())
        menu.addItem(actionItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        statusItem.menu = menu
    }

    private func actionItem(title: String, action: Selector, keyEquivalent: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: keyEquivalent)
        item.target = self
        return item
    }

    private func disabledItem(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }

    private func dashboardURLCandidates() async -> [URL] {
        var ports: [Int] = []
        if let backendPort = await backendPreferredDashboardPort() {
            ports.append(backendPort)
        }
        if let configuredPort = preferredDashboardPort() {
            ports.append(configuredPort)
        }
        ports.append(contentsOf: [3001, 3000])
        var seen = Set<Int>()
        return ports.compactMap { port in
            guard seen.insert(port).inserted else { return nil }
            return URL(string: "http://127.0.0.1:\(port)/")
        }
    }

    private func backendPreferredDashboardPort() async -> Int? {
        guard let url = URL(string: "http://127.0.0.1:8000/api/v1/setup/status") else {
            return nil
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.0
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard
                let http = response as? HTTPURLResponse,
                (200..<300).contains(http.statusCode),
                let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                let runtime = object["runtime_settings"] as? [String: Any],
                let port = runtime["preferred_local_port"] as? Int,
                (1024...65535).contains(port)
            else {
                return nil
            }
            return port
        } catch {
            return nil
        }
    }

    private func preferredDashboardPort() -> Int? {
        let settingsURL = appSupportDirectory().appendingPathComponent("runtime-settings.json")
        guard
            let data = try? Data(contentsOf: settingsURL),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let port = object["preferred_local_port"] as? Int,
            (1024...65535).contains(port)
        else {
            return nil
        }
        return port
    }

    private func firstReachableDashboardURL(from candidates: [URL]) async -> URL? {
        for url in candidates {
            if await dashboardResponds(at: url) {
                return url
            }
        }
        return nil
    }

    private func dashboardResponds(at url: URL) async -> Bool {
        var request = URLRequest(url: url)
        request.httpMethod = "HEAD"
        request.timeoutInterval = 0.8
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { return false }
            return (200..<500).contains(http.statusCode)
        } catch {
            return false
        }
    }

    private func openDashboardURL(_ url: URL) {
        let dashboardURL = dashboardURLWithOpenNonce(url.appendingPathComponent("timeline"))
        debugLog("[Menu] Open Dashboard -> \(dashboardURL.absoluteString)")
        openDashboardWithSafariScript(dashboardURL)
    }

    private func dashboardURLWithOpenNonce(_ url: URL) -> URL {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url
        }
        var items = components.queryItems ?? []
        items.append(URLQueryItem(name: "source", value: "menubar"))
        items.append(URLQueryItem(name: "opened_at", value: "\(Int(Date().timeIntervalSince1970))"))
        components.queryItems = items
        return components.url ?? url
    }

    private func openDashboardWithCommand(_ url: URL) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = [url.absoluteString]
        process.terminationHandler = { [weak self] process in
            self?.debugLog("[Menu] /usr/bin/open exited with status \(process.terminationStatus)")
        }
        do {
            try process.run()
        } catch {
            debugLog("[Menu] /usr/bin/open failed for \(url.absoluteString): \(error)")
        }
    }

    private func openDashboardWithSafariScript(_ url: URL) {
        let process = Process()
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = [
            "-e", "on run argv",
            "-e", "tell application \"Safari\"",
            "-e", "activate",
            "-e", "delay 0.35",
            "-e", "if (count of windows) = 0 then",
            "-e", "make new document with properties {URL:item 1 of argv}",
            "-e", "else",
            "-e", "tell front window",
            "-e", "set newTab to make new tab at end of tabs with properties {URL:item 1 of argv}",
            "-e", "set current tab to newTab",
            "-e", "end tell",
            "-e", "end if",
            "-e", "delay 0.1",
            "-e", "if (count of windows) > 0 then set URL of current tab of front window to item 1 of argv",
            "-e", "end tell",
            "-e", "end run",
            url.absoluteString
        ]
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        process.terminationHandler = { [weak self] process in
            let stdout = String(data: outputPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let stderr = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if process.terminationStatus == 0 {
                self?.debugLog("[Menu] Safari script opened dashboard")
                return
            }
            self?.debugLog("[Menu] Safari script failed status=\(process.terminationStatus) stdout=\(stdout) stderr=\(stderr)")
            self?.openDashboardWithCommand(url)
        }
        do {
            try process.run()
        } catch {
            debugLog("[Menu] Safari script launch failed for \(url.absoluteString): \(error)")
            openDashboardWithCommand(url)
        }
    }

    private func debugLog(_ message: String) {
        let line = "\(DateFormatters.iso8601.string(from: Date())) \(message)\n"
        if let data = line.data(using: .utf8) {
            FileHandle.standardError.write(data)
            let logURL = appSupportDirectory().appendingPathComponent("menu-debug.log")
            if !FileManager.default.fileExists(atPath: logURL.path) {
                FileManager.default.createFile(atPath: logURL.path, contents: nil)
            }
            if let handle = try? FileHandle(forWritingTo: logURL) {
                defer { try? handle.close() }
                _ = try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
            }
        }
    }

    private func appSupportDirectory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let directory = base.appendingPathComponent("WorkdayLens", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }
}

private func copyRawAttribute(_ element: AXUIElement, _ attribute: String) -> CFTypeRef? {
    var value: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
    return result == .success ? value : nil
}

private func containsAny(_ haystack: String, needles: [String]) -> Bool {
    let normalizedHaystack = haystack.lowercased()
    return needles.contains { normalizedHaystack.contains($0.lowercased()) }
}

private func copyStringAttribute(_ element: AXUIElement, _ attribute: String) -> String? {
    if let value = copyRawAttribute(element, attribute) as? String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
    if let value = copyRawAttribute(element, attribute) {
        let string = "\(value)".trimmingCharacters(in: .whitespacesAndNewlines)
        return string.isEmpty ? nil : string
    }
    return nil
}

private func copyBoolAttribute(_ element: AXUIElement, _ attribute: String) -> Bool? {
    copyRawAttribute(element, attribute) as? Bool
}

private func copyElementAttribute(_ element: AXUIElement, _ attribute: String) -> AXUIElement? {
    guard let value = copyRawAttribute(element, attribute) else { return nil }
    return (value as! AXUIElement)
}

extension JSONEncoder.DateEncodingStrategy {
    static var iso8601WithFractionalSeconds: JSONEncoder.DateEncodingStrategy {
        .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(DateFormatters.iso8601.string(from: date))
        }
    }
}

extension JSONDecoder.DateDecodingStrategy {
    static var iso8601WithFractionalSeconds: JSONDecoder.DateDecodingStrategy {
        .custom { decoder in
            let container = try decoder.singleValueContainer()
            let value = try container.decode(String.self)
            if let date = DateFormatters.iso8601.date(from: value) {
                return date
            }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid ISO8601 date: \(value)")
        }
    }
}

enum DateFormatters {
    static let iso8601: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
}

let delegate = AppDelegate()
let app = NSApplication.shared
app.delegate = delegate
app.run()
