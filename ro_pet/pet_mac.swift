import AppKit
import CoreGraphics
import Darwin
import ServiceManagement
import WebKit
#if canImport(Sparkle)
import Sparkle
#endif
final class PetWebView: WKWebView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}
final class FloatingPetPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        return frameRect
    }
}
final class FlippedView: NSView {
    override var isFlipped: Bool { true }
}
enum NativeGlass {
    private final class Geometry: NSObject {
        let frame: NSRect
        let rotation: CGFloat
        init(frame: NSRect, rotation: CGFloat) {
            self.frame = frame
            self.rotation = rotation
        }
    }
    private static let geometry = NSMapTable<NSView, Geometry>.weakToStrongObjects()
    static var forceBlur = false
    static var activeForced = false
    static func kind(active: Bool) -> String {
        #if compiler(>=6.2)
        if #available(macOS 26.0, *), !forceBlur, active || activeForced { return "liquid" }
        #endif
        return "blur"
    }
    static func forceActiveAppearance(_ window: NSWindow) {
        let sel = NSSelectorFromString("_setForceMainAppearance:")
        guard window.responds(to: sel), let m = class_getInstanceMethod(type(of: window), sel) else { return }
        typealias SetBool = @convention(c) (AnyObject, Selector, Bool) -> Void
        unsafeBitCast(method_getImplementation(m), to: SetBool.self)(window, sel, true)
        activeForced = true
    }
    static func make(_ kind: String) -> NSView {
        #if compiler(>=6.2)
        if #available(macOS 26.0, *), kind == "liquid" { return NSGlassEffectView() }
        #endif
        let v = NSVisualEffectView()
        v.blendingMode = .behindWindow
        v.state = .active
        return v
    }
    static func shape(_ v: NSView, frame: NSRect, rotation: CGFloat, alpha: CGFloat, dark: Bool, tint: NSColor?) {
        let appearance: NSAppearance.Name = dark ? .darkAqua : .aqua
        if v.appearance?.name != appearance { v.appearance = NSAppearance(named: appearance) }
        let previous = geometry.object(forKey: v)
        let sizeChanged = previous?.frame.size != frame.size
        if previous?.frame != frame || previous?.rotation != rotation {
            v.frameCenterRotation = 0
            v.frame = frame
            v.frameCenterRotation = rotation
            geometry.setObject(Geometry(frame: frame, rotation: rotation), forKey: v)
        }
        if v.alphaValue != alpha { v.alphaValue = alpha }
        #if compiler(>=6.2)
        if #available(macOS 26.0, *), let g = v as? NSGlassEffectView {
            if g.style != .clear { g.style = .clear }
            if g.cornerRadius != frame.height / 2 { g.cornerRadius = frame.height / 2 }
            let color = tint?.withAlphaComponent(0.46) ?? (dark ? NSColor.black.withAlphaComponent(0.28) : nil)
            if g.tintColor != color { g.tintColor = color }
            return
        }
        #endif
        guard let e = v as? NSVisualEffectView else { return }
        let material: NSVisualEffectView.Material = dark ? .hudWindow : .popover
        if e.material != material { e.material = material }
        if sizeChanged || e.maskImage == nil { e.maskImage = pillMask(frame.size) }
    }
    static func pillMask(_ size: NSSize) -> NSImage {
        NSImage(size: size, flipped: false) { rect in
            NSColor.black.setFill()
            NSBezierPath(roundedRect: rect, xRadius: rect.height / 2, yRadius: rect.height / 2).fill()
            return true
        }
    }
    static func tintColor(_ hex: String?) -> NSColor? {
        guard let hex = hex, hex.range(of: "^#[0-9A-Fa-f]{6}$", options: .regularExpression) != nil,
              let rgb = UInt32(hex.dropFirst(), radix: 16) else { return nil }
        return NSColor(srgbRed: CGFloat((rgb >> 16) & 255) / 255,
                       green: CGFloat((rgb >> 8) & 255) / 255, blue: CGFloat(rgb & 255) / 255, alpha: 1)
    }
}
struct CPUTicks: Equatable {
    var user: UInt32
    var system: UInt32
    var idle: UInt32
    var nice: UInt32
    var busy: UInt32 { user &+ system &+ nice }
    var total: UInt32 { busy &+ idle }
    init(user: UInt32, system: UInt32, idle: UInt32, nice: UInt32) {
        self.user = user
        self.system = system
        self.idle = idle
        self.nice = nice
    }
    init(machTicks t: (UInt32, UInt32, UInt32, UInt32)) {
        self.init(user: t.0, system: t.1, idle: t.2, nice: t.3)
    }
    static func read() -> CPUTicks? {
        var info = host_cpu_load_info()
        var count = mach_msg_type_number_t(MemoryLayout<host_cpu_load_info>.size / MemoryLayout<integer_t>.size)
        let rc = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics(mach_host_self(), HOST_CPU_LOAD_INFO, $0, &count)
            }
        }
        guard rc == KERN_SUCCESS else { return nil }
        return CPUTicks(machTicks: info.cpu_ticks)
    }
}
func cpuPercent(from prev: CPUTicks, to cur: CPUTicks) -> Double? {
    let total = cur.total &- prev.total
    guard total > 0 else { return nil }
    let busy = cur.busy &- prev.busy
    return min(100, Double(busy) / Double(total) * 100)
}
enum Gait: Int, CaseIterable {
    case calm = 0, walk, busy, hot
    static let edges: [Double] = [20, 50, 80]
    var period: Double { [3.2, 1.6, 0.8, 0.4][rawValue] }
    var rate: Double { 3.2 / period }
    var menubarPeriod: Double { max(period, 0.8) }
    var label: String { ["Relaxed", "Steady", "Busy", "Overheating"][rawValue] }
    var jumpHeight: Double { [1.0, 1.6, 2.2, 1.0][rawValue] }
    var squash: Double { [0.08, 0.12, 0.18, 0.10][rawValue] }
    func capped(lowPower: Bool) -> Gait {
        lowPower ? Gait(rawValue: min(rawValue, Gait.walk.rawValue))! : self
    }
}
enum JumpFrame: Int {
    case crouch = 0, rise, apex
}
let jumpSchedule: [(at: Double, frame: JumpFrame)] = [
    (0.00, .crouch), (0.30, .rise), (0.45, .apex), (0.60, .rise), (0.75, .crouch),
]
let iconCanvas: CGFloat = 18
struct IconPose {
    var head: CGRect
    var body: CGRect
    var base: CGRect
    var narrowEyes: Bool
}
func iconPose(_ frame: JumpFrame?, gait: Gait) -> IconPose {
    let s = CGFloat(gait.squash), h = CGFloat(gait.jumpHeight)
    var k: CGFloat = 1, wk: CGFloat = 1
    var lift: (head: CGFloat, body: CGFloat, base: CGFloat) = (0, 0, 0)
    switch frame {
    case .crouch?: k = 1 - s; wk = 1 + s / 2
    case .rise?: k = 1 + s / 3; wk = 1 - s / 4; lift = (0.6 * h, 0.5 * h, 0.4 * h)
    case .apex?: lift = (h, h, h)
    case nil: break
    }
    let x: CGFloat = 2, ground: CGFloat = iconCanvas - 1.3, gap = 0.8 * k
    let baseH = 3.8 * k, bodyH = 3.8 * k, headH = 5.0 * k
    let baseY = ground - baseH, bodyY = baseY - gap - bodyH, headY = bodyY - gap - headH
    return IconPose(
        head: CGRect(x: x, y: headY - lift.head, width: 11.5 * wk, height: headH),
        body: CGRect(x: x, y: bodyY - lift.body, width: 9.1 * wk, height: bodyH),
        base: CGRect(x: x, y: baseY - lift.base, width: 14.0 * wk, height: baseH),
        narrowEyes: gait == .hot
    )
}
struct CPUSmoother {
    static let alpha = 0.3
    static let gap = 5.0
    private(set) var recent: [Double] = []
    private(set) var smoothed: Double? = nil
    private(set) var gait: Gait = .calm
    mutating func push(_ raw: Double) -> Gait {
        recent.append(raw)
        if recent.count > 3 { recent.removeFirst() }
        let median = recent.sorted()[recent.count / 2]
        let value = smoothed.map { Self.alpha * median + (1 - Self.alpha) * $0 } ?? median
        smoothed = value
        while gait != .hot && value >= Gait.edges[gait.rawValue] + Self.gap {
            gait = Gait(rawValue: gait.rawValue + 1)!
        }
        while gait != .calm && value < Gait.edges[gait.rawValue - 1] - Self.gap {
            gait = Gait(rawValue: gait.rawValue - 1)!
        }
        return gait
    }
    mutating func reset() {
        recent = []
        smoothed = nil
        gait = .calm
    }
}
let petSizeScales: [String: CGFloat] = ["small": 0.75, "medium": 1.0, "big": 1.3]
let petBaseCompactSize = NSSize(width: 176, height: 168)
func petCompactSize(_ name: String) -> NSSize {
    let k = petSizeScales[name] ?? 1
    return NSSize(width: (petBaseCompactSize.width * k).rounded(), height: (petBaseCompactSize.height * k).rounded())
}
func petResizeOrigin(frame: NSRect, newSize: NSSize) -> NSPoint {
    NSPoint(x: frame.maxX - newSize.width, y: frame.minY)
}
enum PetMode: String {
    case desktop
    case menubar
}
final class PetAppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    private var panel: FloatingPetPanel!
    private var webView: WKWebView!
    private var glassLayer: FlippedView!
    private var glassViews: [NSView] = []
    private var glassViewsKind = ""
    private var glassKind: String { NativeGlass.kind(active: panel.isKeyWindow) }
    private var statusItem: NSStatusItem!
    private var wanderItem: NSMenuItem!
    private var modeItem: NSMenuItem!
    private var mainMenu: NSMenu!
    private let defaults = UserDefaults(suiteName: "ro.pet") ?? .standard
    private var mode: PetMode = .desktop
    private var urlString: String = "http://127.0.0.1:8765/"
    private var wanderEnabled: Bool = false
#if canImport(Sparkle)
    private var updaterController: SPUStandardUpdaterController?
#endif
    private var lookPrefs = ["panel": "auto"]
    private var pointerInside = false
    private var originBeforeOpen: NSPoint?
    private var lookItems: [NSMenuItem] = []
    private var bubbleOpen: Bool = false
    private var placeTop: Bool = false
    private var placeLeft: Bool = false
    private var wanderDirection: CGFloat = -1.0
    private var wanderTimer: Timer?
    private var dragTimer: Timer?
    private var fallTimer: Timer?
    private var isDragging: Bool = false
    private var sizeName = "medium"
    private var sizeItems: [NSMenuItem] = []
    private var compactSize: NSSize { petCompactSize(sizeName) }
    private let edgeMargin: CGFloat = 6.0
    private let dockZone: CGFloat = 80.0
    private var toastPanel: NSPanel?
    private let popOutDistance: CGFloat = 24.0
    private var iconTimer: Timer?
    private var headerTitle: NSTextField!
    private var headerDetail: NSTextField!
    private var savedDesktopOrigin: NSPoint?
    private var cpuTimer: Timer?
    private var lastTicks: CPUTicks?
    private var smoother = CPUSmoother()
    private(set) var gait: Gait = .calm
    private var iconJumpTimer: Timer?
    private var jumpStep = 0
    private var iconGait: Gait = .calm
    private var iconImages: [Int: NSImage] = [:]
    private var alertPanel: NSPanel?
    private var talkItem: NSMenuItem!
    private var loginItem: NSMenuItem?
    private var matItems: [NSMenuItem] = []
    private var materialName = ""
    private var hitRects: [NSRect] = []
    private var hitReady = false
    private var previewHide: DispatchWorkItem?
    init(url: String, wander: Bool) {
        self.urlString = url
        self.wanderEnabled = wander
        super.init()
    }
    private func setupPointerWatch() {
        panel.acceptsMouseMovedEvents = true
        NSEvent.addGlobalMonitorForEvents(matching: [.mouseMoved, .leftMouseDragged]) { [weak self] _ in self?.forwardPointer() }
        NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            guard let self = self, self.bubbleOpen else { return }
            self.webView.evaluateJavaScript("window.toggleBubbleFromHost && window.toggleBubbleFromHost(false);", completionHandler: nil)
        }
        NSEvent.addLocalMonitorForEvents(matching: .mouseMoved) { [weak self] event in
            self?.forwardPointer()
            return event
        }
    }
    private func forwardPointer() {
        updateClickThrough()
        let mouse = NSEvent.mouseLocation
        let frame = panel.frame
        guard panel.isVisible, frame.contains(mouse) else {
            if pointerInside {
                pointerInside = false
                webView.evaluateJavaScript("window.onHostPointer && window.onHostPointer(null);", completionHandler: nil)
            }
            return
        }
        pointerInside = true
        let x = mouse.x - frame.minX, y = frame.maxY - mouse.y
        webView.evaluateJavaScript("window.onHostPointer && window.onHostPointer(\(x), \(y));", completionHandler: nil)
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        killOtherInstances()
        NSApp.setActivationPolicy(.accessory)
        mode = PetMode(rawValue: defaults.string(forKey: "ro.mode") ?? "") ?? .desktop
        if let saved = defaults.string(forKey: "ro.size"), petSizeScales[saved] != nil { sizeName = saved }
        if wanderEnabled, defaults.object(forKey: "ro.wander") != nil {
            wanderEnabled = defaults.bool(forKey: "ro.wander")
        }
#if canImport(Sparkle)
        if Bundle.main.object(forInfoDictionaryKey: "SUFeedURL") != nil {
            updaterController = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: self, userDriverDelegate: nil)
        }
#endif
        setupStatusItem()
        setupFloatingPanel()
        setupPointerWatch()
        setMode(mode)
        ensureIconVisible(announceSuccess: false)
        setupWanderTimer()
        setupCPUSampler()
        observeIconConditions()
    }
    private func killOtherInstances() {
        let myPid = ProcessInfo.processInfo.processIdentifier
        for app in NSWorkspace.shared.runningApplications {
            if app.processIdentifier != myPid,
               app.executableURL?.lastPathComponent == "ro-pet-host" {
                app.forceTerminate()
            }
        }
    }
    private func bringPanelForward() {
        panel.orderFrontRegardless()
    }
    private func updateClickThrough() {
        guard let panel = panel else { return }
        guard hitReady, !isDragging, panel.isVisible else {
            if panel.ignoresMouseEvents { panel.ignoresMouseEvents = false }
            return
        }
        let mouse = NSEvent.mouseLocation, frame = panel.frame
        let point = NSPoint(x: mouse.x - frame.minX, y: frame.maxY - mouse.y)
        let inside = hitRects.contains { $0.contains(point) }
        if panel.ignoresMouseEvents == inside { panel.ignoresMouseEvents = !inside }
    }
    private func currentVisibleFrame() -> NSRect {
        if let s = panel?.screen ?? NSScreen.main ?? NSScreen.screens.first {
            return s.visibleFrame
        }
        return NSRect(x: 0, y: 0, width: 1440, height: 900)
    }
    private func clampOrigin(_ origin: NSPoint, size: NSSize) -> NSPoint {
        let vf = currentVisibleFrame()
        let minX = vf.minX + edgeMargin
        let maxX = max(minX, vf.maxX - size.width - edgeMargin)
        let minY = vf.minY + edgeMargin
        let maxY = max(minY, vf.maxY - size.height - edgeMargin)
        return NSPoint(
            x: min(max(origin.x, minX), maxX),
            y: min(max(origin.y, minY), maxY)
        )
    }
    private func currentPetOrigin() -> NSPoint {
        let f = panel.frame
        if !bubbleOpen {
            return f.origin
        }
        let x = placeLeft ? f.minX : (f.maxX - compactSize.width)
        let y = placeTop ? (f.maxY - compactSize.height) : f.minY
        return NSPoint(x: x, y: y)
    }
    private func setBubbleState(_ open: Bool) {
        if bubbleOpen == open { return }
        let petPos = clampOrigin(currentPetOrigin(), size: compactSize)
        bubbleOpen = open
        talkItem?.title = (open ? "Close panel" : "Open panel")
        if open {
            let vf = currentVisibleFrame()
            let expandedSize = NSSize(width: 388, height: min(760, vf.height * 0.88))
            placeTop = (petPos.y + expandedSize.height > vf.maxY - edgeMargin)
            placeLeft = (petPos.x + compactSize.width - expandedSize.width < vf.minX + edgeMargin)
            webView.evaluateJavaScript(
                "window.setBubblePlacement && window.setBubblePlacement(\(placeTop), \(placeLeft));",
                completionHandler: nil
            )
            let rawX = placeLeft ? petPos.x : (petPos.x + compactSize.width - expandedSize.width)
            let rawY = placeTop ? (petPos.y + compactSize.height - expandedSize.height) : petPos.y
            let newOrigin = clampOrigin(NSPoint(x: rawX, y: rawY), size: expandedSize)
            originBeforeOpen = petPos
            let newFrame = NSRect(origin: newOrigin, size: expandedSize)
            panel.setFrame(newFrame, display: true)
            webView.frame = NSRect(origin: .zero, size: expandedSize)
            refreshGlass()
            bringPanelForward()
        } else {
            webView.evaluateJavaScript(
                "window.setBubblePlacement && window.setBubblePlacement(false, false);",
                completionHandler: nil
            )
            let newOrigin = clampOrigin(originBeforeOpen ?? petPos, size: compactSize)
            originBeforeOpen = nil
            let newFrame = NSRect(origin: newOrigin, size: compactSize)
            panel.setFrame(newFrame, display: true)
            webView.frame = NSRect(origin: .zero, size: compactSize)
            refreshGlass()
            revealPet()
        }
    }
    private func startNativeDrag(fromPet: Bool) {
        dragTimer?.invalidate()
        let startMouse = NSEvent.mouseLocation
        let startOrigin = panel.frame.origin
        var moved = false
        var tick = 0
        let canDock = fromPet && mode == .desktop && !bubbleOpen
        var inZone = false
        var lastProgress: CGFloat = 0
        isDragging = true
        if fromPet {
            NSHapticFeedbackManager.defaultPerformer.perform(.generic, performanceTime: .now)
            webView.evaluateJavaScript(
                "window.onHostDragStart && window.onHostDragStart(true);",
                completionHandler: nil
            )
        }
        let timer = Timer(timeInterval: 0.008, repeats: true) { [weak self] timer in
            guard let self = self else {
                timer.invalidate()
                return
            }
            let curMouse = NSEvent.mouseLocation
            let dx = curMouse.x - startMouse.x
            let dy = curMouse.y - startMouse.y
            tick += 1
            if hypot(dx, dy) > 8.0 {
                moved = true
                self.originBeforeOpen = nil
            }
            if moved {
                let target = NSPoint(x: startOrigin.x + dx, y: startOrigin.y + dy)
                let clamped = self.clampOrigin(target, size: self.panel.frame.size)
                self.panel.setFrameOrigin(clamped)
                if fromPet && tick % 2 == 0 {
                    self.webView.evaluateJavaScript(
                        "window.onHostDragMove && window.onHostDragMove(\(clamped.x), \(-clamped.y));",
                        completionHandler: nil
                    )
                }
            }
            if canDock && moved {
                let top = (self.panel.screen ?? NSScreen.main)?.visibleFrame.maxY ?? curMouse.y
                let d = max(0, top - curMouse.y)
                let nowIn = d < self.dockZone
                if nowIn != inZone {
                    inZone = nowIn
                    if nowIn { self.pinStatusItemFirst() }
                    self.statusItem.isVisible = nowIn
                }
                let progress = nowIn ? min(1, 1 - d / self.dockZone) : 0
                if abs(progress - lastProgress) > 0.02 || (progress == 0) != (lastProgress == 0) {
                    lastProgress = progress
                    self.webView.evaluateJavaScript(
                        "window.onHostDockProgress && window.onHostDockProgress(\(String(format: "%.3f", progress)));",
                        completionHandler: nil
                    )
                }
            }
            if (NSEvent.pressedMouseButtons & 1) == 0 {
                timer.invalidate()
                self.dragTimer = nil
                self.isDragging = false
                if inZone {
                    self.dockToMenubar(returnOrigin: startOrigin)
                    return
                }
                if moved && self.mode == .desktop { self.savePosition(delay: 0.5) }
                if fromPet {
                    let fall = moved ? self.startFall() : 0
                    self.webView.evaluateJavaScript(
                        "window.onHostDragEnd && window.onHostDragEnd(\(moved), \(fall));",
                        completionHandler: nil
                    )
                }
                if !moved && fromPet {
                    self.webView.evaluateJavaScript(
                        "window.onPetClickFromHost && window.onPetClickFromHost();",
                        completionHandler: nil
                    )
                }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        dragTimer = timer
    }
    private func startFall() -> CGFloat {
        let g: CGFloat = 2400
        let maxFall: CGFloat = 24
        let floorY = currentVisibleFrame().minY + edgeMargin
        let startY = panel.frame.origin.y
        let fall = min(max(0, startY - floorY), maxFall)
        if fall < 0.5 { return 0 }
        let duration = sqrt(2 * fall / g)
        let startX = panel.frame.origin.x
        let begin = Date()
        fallTimer?.invalidate()
        fallTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 120.0, repeats: true) { [weak self] timer in
            guard let self = self else { timer.invalidate(); return }
            let t = CGFloat(Date().timeIntervalSince(begin))
            if t >= duration {
                self.panel.setFrameOrigin(NSPoint(x: startX, y: startY - fall))
                timer.invalidate()
                self.fallTimer = nil
                return
            }
            self.panel.setFrameOrigin(NSPoint(x: startX, y: startY - 0.5 * g * t * t))
        }
        return fall
    }
    private func dockToMenubar(returnOrigin: NSPoint) {
        guard let iconFrame = statusItem.button?.window?.frame else {
            setMode(.menubar)
            return
        }
        let size = panel.frame.size
        let target = NSPoint(x: iconFrame.midX - size.width / 2, y: iconFrame.midY - size.height / 2)
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.28
            ctx.timingFunction = CAMediaTimingFunction(name: .easeOut)
            self.panel.animator().setFrameOrigin(target)
        }, completionHandler: { [weak self] in
            guard let self = self else { return }
            self.setMode(.menubar)
            self.panel.setFrameOrigin(self.clampOrigin(returnOrigin, size: size))
            self.webView.evaluateJavaScript("window.onHostDocked && window.onHostDocked();", completionHandler: nil)
            self.bounceIcon()
            self.ensureIconVisible(announceSuccess: true)
        })
    }
    private func ensureIconVisible(announceSuccess: Bool) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            guard let self = self, self.mode == .menubar,
                  let win = self.statusItem.button?.window else { return }
            if win.occlusionState.contains(.visible) {
                if announceSuccess {
                    self.showToast("Moved to the menu bar", "Drag the icon down to bring it back")
                }
            } else if NSMenu.menuBarVisible() {
                self.setMode(.desktop)
                self.showToast("The menu bar is full", "The icon would hide behind the notch, so ro stayed on the desktop")
            }
        }
    }
    private func bounceIcon() {
        guard let btn = statusItem.button else { return }
        btn.image = makeIcon(iconPose(.apex, gait: .walk))
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { [weak self] in
            self?.statusItem.button?.image = self?.makeIcon(iconPose(nil, gait: .calm))
        }
    }
    private func showToast(_ title: String, _ detail: String) {
        toastPanel?.orderOut(nil)
        let label = NSTextField(labelWithAttributedString: {
            let s = NSMutableAttributedString(string: title + "\n", attributes: [.font: NSFont.boldSystemFont(ofSize: 13)])
            s.append(NSAttributedString(string: detail, attributes: [
                .font: NSFont.systemFont(ofSize: 11), .foregroundColor: NSColor.secondaryLabelColor
            ]))
            return s
        }())
        label.sizeToFit()
        let size = NSSize(width: label.frame.width + 32, height: label.frame.height + 22)
        let box = NSVisualEffectView(frame: NSRect(origin: .zero, size: size))
        box.material = .popover
        box.state = .active
        box.wantsLayer = true
        box.layer?.cornerRadius = 12
        label.frame.origin = NSPoint(x: 16, y: 11)
        box.addSubview(label)
        let vf = (statusItem.button?.window?.screen ?? NSScreen.main)?.visibleFrame ?? .zero
        let anchorX = statusItem.isVisible ? (statusItem.button?.window?.frame.midX ?? vf.midX) : vf.midX
        let x = min(max(anchorX - size.width / 2, vf.minX + 8), vf.maxX - size.width - 8)
        let toast = NSPanel(contentRect: NSRect(x: x, y: vf.maxY - size.height - 8, width: size.width, height: size.height),
                            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        toast.isOpaque = false
        toast.backgroundColor = .clear
        toast.hasShadow = true
        toast.level = .statusBar
        toast.ignoresMouseEvents = true
        toast.contentView = box
        toast.orderFrontRegardless()
        toastPanel = toast
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.6) { [weak self, weak toast] in
            toast?.orderOut(nil)
            if self?.toastPanel === toast { self?.toastPanel = nil }
        }
    }
    private func makeIcon(_ pose: IconPose) -> NSImage {
        let img = NSImage(size: NSSize(width: iconCanvas, height: iconCanvas), flipped: true) { _ in
            let ink = NSColor(calibratedRed: 0x1A/255.0, green: 0x19/255.0, blue: 0x17/255.0, alpha: 1.0)
            ink.setFill()
            let px = max(1, NSGraphicsContext.current?.cgContext.ctm.a ?? 2)
            func round(_ v: CGFloat) -> CGFloat { (v * px).rounded() / px }
            func snap(_ r: NSRect) -> NSRect {
                NSRect(x: round(r.minX), y: round(r.minY), width: max(1 / px, round(r.width)), height: max(1 / px, round(r.height)))
            }
            let base = snap(pose.base)
            var body = snap(pose.body)
            body.origin.y = base.minY - max(1 / px, round(pose.base.minY - pose.body.maxY)) - body.height
            var head = snap(pose.head)
            head.origin.y = body.minY - max(1 / px, round(pose.body.minY - pose.head.maxY)) - head.height
            for r in [head, body, base] {
                let radius = min(r.height / 2, 2.5)
                NSBezierPath(roundedRect: r, xRadius: radius, yRadius: radius).fill()
            }
            let hd = head
            let eyes = pose.narrowEyes
                ? [NSRect(x: hd.minX + 5.3, y: hd.minY + hd.height * 0.42, width: 1.7, height: 1.0),
                   NSRect(x: hd.minX + 7.9, y: hd.minY + hd.height * 0.42, width: 1.5, height: 1.0)]
                : [NSRect(x: hd.minX + 5.5, y: hd.minY + hd.height * 0.24, width: 1.3, height: hd.height * 0.5),
                   NSRect(x: hd.minX + 8.0, y: hd.minY + hd.height * 0.28, width: 1.2, height: hd.height * 0.42)]
            NSGraphicsContext.current?.compositingOperation = .clear
            func snapEye(_ e: NSRect) -> NSRect {
                let w = max(1 / px, round(e.width)), h = max(1 / px, (e.height * px).rounded(.down) / px)
                return NSRect(x: round(e.midX - w / 2), y: round(e.midY - h / 2), width: w, height: h)
            }
            for e in eyes.map(snapEye) {
                NSBezierPath(roundedRect: e, xRadius: 0.5, yRadius: 0.5).fill()
            }
            NSGraphicsContext.current?.compositingOperation = .sourceOver
            return true
        }
        img.isTemplate = true
        return img
    }
    private let statusAutosaveName = "ro.pet"
    private func pinStatusItemFirst() {
        UserDefaults.standard.set(1, forKey: "NSStatusItem Preferred Position \(statusAutosaveName)")
    }
    private func setupStatusItem() {
        if statusItem == nil {
        pinStatusItemFirst()
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.autosaveName = statusAutosaveName
        if let btn = statusItem.button {
            btn.target = self
            btn.action = #selector(statusButtonPressed)
            btn.sendAction(on: [.leftMouseDown, .rightMouseDown])
            btn.image = makeIcon(iconPose(nil, gait: .calm))
            btn.toolTip = "ro — three layers, two eyes."
        }
        }
        lookItems = []; sizeItems = []; matItems = []
        let menu = NSMenu()
        menu.addItem(makeHeaderItem())
        menu.addItem(NSMenuItem.separator())
        talkItem = NSMenuItem(title: (bubbleOpen ? "Close panel" : "Open panel"), action: #selector(toggleBubble), keyEquivalent: "k")
        talkItem.target = self
        menu.addItem(talkItem)
        let previewMenu = NSMenu()
        let moods: [(String, String)] = [
            ("Idle", "idle"), ("Recording", "recording"), ("Focus", "focus"),
            ("Attention", "anxious"), ("Discovery", "discovery"), ("Resolved", "resolved")
        ]
        previewMenu.addItem(menuSection("Expression"))
        for (title, code) in moods {
            let item = NSMenuItem(title: title, action: #selector(previewMood(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = code
            previewMenu.addItem(item)
        }
        let actions: [(String, String)] = [
            ("Breathe", "breathe"), ("Look around", "look_around"), ("Walk", "walk"), ("Think", "thinking"),
            ("Startle", "alert"), ("Drowsy", "drowsy"), ("Gaze", "gaze"), ("Press", "press"), ("Pet", "pet"),
            ("Drag", "drag"), ("Shake", "shake"), ("Land", "drop"), ("Success", "success"), ("Failure", "failure")
        ]
        previewMenu.addItem(NSMenuItem.separator())
        previewMenu.addItem(menuSection("Motion"))
        for (title, code) in actions {
            let item = NSMenuItem(title: title, action: #selector(triggerActionFromMenu(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = code
            previewMenu.addItem(item)
        }
        let previewRoot = NSMenuItem(title: "Preview expressions & motion", action: nil, keyEquivalent: "")
        previewRoot.submenu = previewMenu
        let matMenu = NSMenu()
        let materials: [(String, String)] = [
            ("Clay", "clay"), ("Glass", "glass")
        ]
        for (title, code) in materials {
            let item = NSMenuItem(title: title, action: #selector(selectMaterial(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = code
            item.state = materialName == code ? .on : .off
            matItems.append(item)
            matMenu.addItem(item)
        }
        let matRoot = NSMenuItem(title: "Material", action: nil, keyEquivalent: "")
        matRoot.submenu = matMenu
        menu.addItem(NSMenuItem.separator())
        menu.addItem(matRoot)
        let sizeMenu = NSMenu()
        for (title, code) in [("Small", "small"), ("Medium", "medium"), ("Big", "big")] {
            let item = NSMenuItem(title: title, action: #selector(selectSize(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = code
            item.state = sizeName == code ? .on : .off
            sizeItems.append(item)
            sizeMenu.addItem(item)
        }
        let sizeRoot = NSMenuItem(title: "Size", action: nil, keyEquivalent: "")
        sizeRoot.submenu = sizeMenu
        menu.addItem(sizeRoot)
        let lookMenu = NSMenu()
        let looks: [(String, [(String, String)])] = [
            ("panel", [("System", "auto"), ("Light", "light"), ("Dark", "dark")])
        ]
        for (key, choices) in looks {
            for (label, value) in choices {
                let item = NSMenuItem(title: label, action: #selector(selectLook(_:)), keyEquivalent: "")
                item.target = self
                item.representedObject = [key, value]
                item.state = lookPrefs[key] == value ? .on : .off
                lookItems.append(item)
                lookMenu.addItem(item)
            }
        }
        let lookRoot = NSMenuItem(title: "Panel color", action: nil, keyEquivalent: "")
        lookRoot.submenu = lookMenu
        menu.addItem(lookRoot)
        wanderItem = NSMenuItem(title: "Wander", action: #selector(toggleWander), keyEquivalent: "w")
        wanderItem.target = self
        wanderItem.state = wanderEnabled ? .on : .off
        menu.addItem(wanderItem)
        menu.addItem(previewRoot)
        modeItem = NSMenuItem(title: (mode == .menubar ? "Bring to desktop" : "Send to menu bar"), action: #selector(toggleMode), keyEquivalent: "")
        modeItem.target = self
        menu.addItem(modeItem)
        let resetItem = NSMenuItem(title: "Call to bottom right", action: #selector(resetPosition), keyEquivalent: "0")
        resetItem.target = self
        menu.addItem(resetItem)
        if #available(macOS 13.0, *), Bundle.main.bundleURL.pathExtension == "app" {
            let item = NSMenuItem(title: "Open at login", action: #selector(toggleLoginItem), keyEquivalent: "")
            item.target = self
            item.state = SMAppService.mainApp.status == .enabled ? .on : .off
            loginItem = item
            menu.addItem(item)
        }
#if canImport(Sparkle)
        if let updaterController = updaterController {
            let updateItem = NSMenuItem(title: "Check for updates…", action: #selector(SPUStandardUpdaterController.checkForUpdates(_:)), keyEquivalent: "")
            updateItem.target = updaterController
            menu.addItem(updateItem)
        }
#endif
        menu.addItem(NSMenuItem.separator())
        let quitItem = NSMenuItem(title: "Quit ro pet", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        mainMenu = menu
    }
    private func makeHeaderItem() -> NSMenuItem {
        headerTitle = NSTextField(labelWithString: "ro.bot")
        headerTitle.font = NSFont.boldSystemFont(ofSize: 13)
        headerDetail = NSTextField(labelWithString: "Measuring CPU")
        headerDetail.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        headerDetail.textColor = .secondaryLabelColor
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 240, height: 44))
        headerTitle.frame = NSRect(x: 14, y: 22, width: 220, height: 17)
        headerDetail.frame = NSRect(x: 14, y: 5, width: 220, height: 15)
        view.addSubview(headerTitle)
        view.addSubview(headerDetail)
        let item = NSMenuItem()
        item.view = view
        return item
    }
    @objc private func toggleLoginItem() {
        guard #available(macOS 13.0, *) else { return }
        do {
            if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
            else { try SMAppService.mainApp.register() }
        } catch {
            showToast("Could not change the login setting", "Check System Settings › General › Login Items")
        }
        loginItem?.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }
    @objc private func statusButtonPressed() {
        guard let event = NSApp.currentEvent, let btn = statusItem.button else { return }
        if event.type == .rightMouseDown {
            showStatusMenu()
            return
        }
        let start = NSEvent.mouseLocation
        iconTimer?.invalidate()
        let timer = Timer(timeInterval: 0.008, repeats: true) { [weak self] timer in
            guard let self = self else {
                timer.invalidate()
                return
            }
            let cur = NSEvent.mouseLocation
            if start.y - cur.y > self.popOutDistance {
                timer.invalidate()
                self.iconTimer = nil
                btn.highlight(false)
                self.popOut(at: cur)
            } else if (NSEvent.pressedMouseButtons & 1) == 0 {
                timer.invalidate()
                self.iconTimer = nil
                self.showStatusMenu()
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        iconTimer = timer
    }
    private func showStatusMenu() {
        guard let btn = statusItem.button, let win = btn.window else { return }
        btn.highlight(true)
        mainMenu.popUp(positioning: nil, at: NSPoint(x: win.frame.minX, y: win.frame.minY - 4), in: nil)
        btn.highlight(false)
    }
    private func popOut(at mouse: NSPoint) {
        savedDesktopOrigin = nil
        panel.setFrameOrigin(NSPoint(x: mouse.x - compactSize.width / 2, y: mouse.y - compactSize.height + 40))
        setMode(.desktop)
        startNativeDrag(fromPet: true)
    }
    private func menubarAnchorOrigin() -> NSPoint {
        let vf = currentVisibleFrame()
        let midX = statusItem.button?.window?.frame.midX ?? (vf.maxX - compactSize.width / 2)
        return NSPoint(x: midX - compactSize.width / 2, y: vf.maxY - compactSize.height)
    }
    private func setMode(_ next: PetMode) {
        if next != mode && bubbleOpen {
            webView.evaluateJavaScript("window.toggleBubbleFromHost && window.toggleBubbleFromHost(false);", completionHandler: nil)
            setBubbleState(false)
        }
        if next == .desktop, let origin = savedDesktopOrigin {
            panel.setFrameOrigin(origin)
            savedDesktopOrigin = nil
        }
        if next == .desktop { fitPanelToCompactSize() }
        mode = next
        defaults.set(next.rawValue, forKey: "ro.mode")
        if next == .menubar { pinStatusItemFirst() }
        statusItem.isVisible = (next == .menubar)
        DispatchQueue.main.async { [weak self] in self?.updateIconAnimation() }
        modeItem.title = (next == .menubar ? "Bring to desktop" : "Send to menu bar")
        if next == .menubar {
            panel.orderOut(nil)
        } else {
            panel.orderFrontRegardless()
        }
    }
    private func revealPet() {
        if mode == .desktop || bubbleOpen {
            panel.orderFrontRegardless()
        } else {
            panel.orderOut(nil)
        }
    }
    private func revealPetForPreview(seconds: TimeInterval) {
        previewHide?.cancel()
        previewHide = nil
        guard mode == .menubar, !bubbleOpen else { revealPet(); return }
        savedDesktopOrigin = savedDesktopOrigin ?? panel.frame.origin
        fitPanelToCompactSize()
        panel.setFrameOrigin(menubarAnchorOrigin())
        panel.orderFrontRegardless()
        let work = DispatchWorkItem { [weak self] in
            guard let self = self else { return }
            self.previewHide = nil
            self.revealPet()
        }
        previewHide = work
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
    }
    @objc private func toggleMode() {
        setMode(mode == .desktop ? .menubar : .desktop)
    }
    private func setupFloatingPanel() {
        let vf = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        var origin = NSPoint(x: vf.maxX - compactSize.width - 20, y: vf.minY + 18)
        if defaults.object(forKey: "ro.pos.x") != nil {
            let saved = NSPoint(x: defaults.double(forKey: "ro.pos.x"), y: defaults.double(forKey: "ro.pos.y"))
            let r = NSRect(origin: saved, size: compactSize)
            if NSScreen.screens.contains(where: { $0.visibleFrame.intersects(r.insetBy(dx: 40, dy: 40)) }) {
                origin = saved
            }
        }
        let rect = NSRect(origin: origin, size: compactSize)
        panel = FloatingPetPanel(
            contentRect: rect,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces]
        panel.isMovableByWindowBackground = false
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "roHost")
        webView = PetWebView(frame: NSRect(origin: .zero, size: compactSize), configuration: config)
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        webView.autoresizingMask = [.width, .height]
        NativeGlass.forceBlur = defaults.string(forKey: "ro.glass") == "blur"
        if !NativeGlass.forceBlur { NativeGlass.forceActiveAppearance(panel) }
        let container = FlippedView(frame: NSRect(origin: .zero, size: compactSize))
        glassLayer = FlippedView(frame: container.bounds)
        glassLayer.autoresizingMask = [.width, .height]
        glassLayer.isHidden = true
        container.addSubview(glassLayer)
        container.addSubview(webView)
        panel.contentView = container
        for name in [NSWindow.didBecomeKeyNotification, NSWindow.didResignKeyNotification] {
            NotificationCenter.default.addObserver(forName: name, object: panel, queue: .main) { [weak self] _ in
                self?.refreshGlass()
            }
        }
        if let url = URL(string: urlString) {
            webView.load(URLRequest(url: url))
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let home = URL(string: urlString)
        let target = navigationAction.request.url
        let sameOrigin = target?.scheme == home?.scheme && target?.host == home?.host && target?.port == home?.port
        decisionHandler(sameOrigin || target?.absoluteString == "about:blank" ? .allow : .cancel)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.evaluateJavaScript("window.setWanderState && window.setWanderState(\(wanderEnabled));", completionHandler: nil)
        webView.evaluateJavaScript("window.setPetSize && window.setPetSize('\(sizeName)');", completionHandler: nil)
        webView.evaluateJavaScript("window.setNativeGlass && window.setNativeGlass('\(glassKind)');", completionHandler: nil)
    }
    private func refreshGlass() {
        glassLayer.isHidden = true
        webView.evaluateJavaScript("window.setNativeGlass && window.setNativeGlass('\(glassKind)');", completionHandler: nil)
    }
    private func updateGlass(on: Bool, rects: [[Double]], dark: Bool, tint: String?) {
        guard on, rects.count == 3, rects.allSatisfy({ $0.count == 6 }) else {
            glassLayer.isHidden = true
            return
        }
        let kind = glassKind
        if glassViewsKind != kind {
            glassViews.forEach { $0.removeFromSuperview() }
            glassViews = []
            glassViewsKind = kind
        }
        while glassViews.count < rects.count {
            let v = NativeGlass.make(kind)
            glassLayer.addSubview(v)
            glassViews.append(v)
        }
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        let color = NativeGlass.tintColor(tint)
        for (v, r) in zip(glassViews, rects) {
            NativeGlass.shape(v, frame: NSRect(x: r[0], y: r[1], width: r[2], height: r[3]),
                              rotation: CGFloat(r[4]), alpha: CGFloat(r[5]), dark: dark, tint: color)
        }
        CATransaction.commit()
        glassLayer.isHidden = false
    }
    private func setupWanderTimer() {
        wanderTimer = Timer.scheduledTimer(withTimeInterval: 3.2, repeats: true) { [weak self] _ in
            guard let self = self, self.mode == .desktop, self.wanderEnabled, !self.bubbleOpen, !self.isDragging else { return }
            let vf = self.currentVisibleFrame()
            var frame = self.panel.frame
            let step: CGFloat = 14.0 * self.wanderDirection
            var nextX = frame.origin.x + step
            let minX = vf.minX + 16
            let maxX = max(minX, vf.maxX - frame.width - 16)
            if nextX <= minX {
                nextX = minX
                self.wanderDirection = 1.0
            } else if nextX >= maxX {
                nextX = maxX
                self.wanderDirection = -1.0
            }
            frame.origin = self.clampOrigin(NSPoint(x: nextX, y: frame.origin.y), size: frame.size)
            self.panel.setFrame(frame, display: true, animate: true)
        }
    }
    private func setupCPUSampler() {
        let nc = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.screensDidSleepNotification, NSWorkspace.sessionDidResignActiveNotification] {
            nc.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in self?.stopCPUSampler() }
        }
        for name in [NSWorkspace.screensDidWakeNotification, NSWorkspace.sessionDidBecomeActiveNotification] {
            nc.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in self?.startCPUSampler() }
        }
        startCPUSampler()
    }
    private func startCPUSampler() {
        stopCPUSampler()
        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in self?.sampleCPU() }
        timer.tolerance = 0.3
        RunLoop.main.add(timer, forMode: .common)
        cpuTimer = timer
    }
    private func stopCPUSampler() {
        cpuTimer?.invalidate()
        cpuTimer = nil
        lastTicks = nil
        smoother.reset()
    }
    private func sampleCPU() {
        guard let cur = CPUTicks.read() else { return }
        defer { lastTicks = cur }
        guard let prev = lastTicks, let pct = cpuPercent(from: prev, to: cur) else { return }
        let next = smoother.push(pct)
        if next != gait {
            gait = next
            updateIconAnimation()
        }
        let shown = Int((smoother.smoothed ?? pct).rounded())
        headerDetail.stringValue = "CPU \(shown)% · \(gait.label)"
    }
    private func updateIconAnimation() {
        let visible = statusItem.button?.window?.occlusionState.contains(.visible) ?? false
        let animate = mode == .menubar && visible && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        guard animate else {
            iconJumpTimer?.invalidate()
            iconJumpTimer = nil
            jumpStep = 0
            statusItem.button?.image = makeIcon(iconPose(nil, gait: .calm))
            return
        }
        if iconJumpTimer == nil {
            jumpStep = 0
            iconGait = targetIconGait()
            showJumpStep()
        }
    }
    private func targetIconGait() -> Gait {
        gait.capped(lowPower: ProcessInfo.processInfo.isLowPowerModeEnabled)
    }
    private func showJumpStep() {
        let step = jumpSchedule[jumpStep]
        statusItem.button?.image = jumpImage(step.frame, gait: iconGait)
        let nextAt = jumpStep + 1 < jumpSchedule.count ? jumpSchedule[jumpStep + 1].at : 1.0
        let delay = (nextAt - step.at) * iconGait.menubarPeriod
        let timer = Timer(timeInterval: delay, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            self.jumpStep = (self.jumpStep + 1) % jumpSchedule.count
            if self.jumpStep == 0 {
                self.iconGait = self.targetIconGait()
            }
            self.showJumpStep()
        }
        timer.tolerance = delay * 0.1
        RunLoop.main.add(timer, forMode: .common)
        iconJumpTimer = timer
    }
    private func jumpImage(_ frame: JumpFrame, gait g: Gait) -> NSImage {
        let key = g.rawValue * 3 + frame.rawValue
        if let img = iconImages[key] { return img }
        let img = makeIcon(iconPose(frame, gait: g))
        iconImages[key] = img
        return img
    }
    private func observeIconConditions() {
        let refresh: (Notification) -> Void = { [weak self] _ in self?.updateIconAnimation() }
        NotificationCenter.default.addObserver(forName: Notification.Name.NSProcessInfoPowerStateDidChange,
                                               object: nil, queue: .main, using: refresh)
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification, object: nil, queue: .main, using: refresh)
        NotificationCenter.default.addObserver(forName: NSWindow.didChangeOcclusionStateNotification,
                                               object: nil, queue: .main) { [weak self] note in
            guard let self = self, (note.object as? NSWindow) === self.statusItem.button?.window else { return }
            self.updateIconAnimation()
        }
    }
    @objc private func toggleBubble() {
        if mode == .menubar && !bubbleOpen {
            savedDesktopOrigin = savedDesktopOrigin ?? panel.frame.origin
            panel.setFrameOrigin(menubarAnchorOrigin())
        }
        bringPanelForward()
        webView.evaluateJavaScript("window.toggleBubbleFromHost && window.toggleBubbleFromHost();", completionHandler: nil)
    }
    @objc private func previewMood(_ sender: NSMenuItem) {
        guard let code = sender.representedObject as? String else { return }
        revealPetForPreview(seconds: 10)
        webView.evaluateJavaScript("window.setMoodPreview && window.setMoodPreview('\(code)', 10000);", completionHandler: nil)
    }
    @objc private func triggerActionFromMenu(_ sender: NSMenuItem) {
        guard let code = sender.representedObject as? String else { return }
        revealPetForPreview(seconds: 5)
        webView.evaluateJavaScript("window.triggerAction && window.triggerAction('\(code)', 4500);", completionHandler: nil)
    }
    @objc private func selectMaterial(_ sender: NSMenuItem) {
        guard let code = sender.representedObject as? String else { return }
        revealPet()
        webView.evaluateJavaScript("window.setMaterialFromHost && window.setMaterialFromHost('\(code)');", completionHandler: nil)
    }
    @objc private func selectLook(_ sender: NSMenuItem) {
        guard let choice = sender.representedObject as? [String], choice.count == 2 else { return }
        webView.evaluateJavaScript("window.setLookPref && window.setLookPref('\(choice[0])', '\(choice[1])');", completionHandler: nil)
    }
    @objc private func selectSize(_ sender: NSMenuItem) {
        guard let code = sender.representedObject as? String else { return }
        applySize(code)
    }
    private func applySize(_ code: String) {
        guard petSizeScales[code] != nil else { return }
        sizeName = code
        defaults.set(code, forKey: "ro.size")
        for item in sizeItems { item.state = (item.representedObject as? String) == code ? .on : .off }
        webView?.evaluateJavaScript("window.setPetSize && window.setPetSize('\(code)');", completionHandler: nil)
        guard panel != nil else { return }
        if bubbleOpen {
            originBeforeOpen = nil
            return
        }
        guard mode == .desktop else { return }
        fitPanelToCompactSize()
        savePosition(delay: 0.2)
    }
    private func fitPanelToCompactSize() {
        let size = compactSize
        guard !bubbleOpen, panel.frame.size != size else { return }
        let origin = clampOrigin(petResizeOrigin(frame: panel.frame, newSize: size), size: size)
        panel.setFrame(NSRect(origin: origin, size: size), display: true, animate: false)
        webView.frame = NSRect(origin: .zero, size: size)
        refreshGlass()
    }
    @objc private func toggleWander() {
        wanderEnabled.toggle()
        wanderItem.state = wanderEnabled ? .on : .off
        defaults.set(wanderEnabled, forKey: "ro.wander")
        webView?.evaluateJavaScript("window.setWanderState && window.setWanderState(\(wanderEnabled));", completionHandler: nil)
    }
    @objc private func resetPosition() {
        if mode == .menubar {
            setMode(.desktop)
        }
        if bubbleOpen {
            webView.evaluateJavaScript("window.toggleBubbleFromHost && window.toggleBubbleFromHost(false);", completionHandler: nil)
            setBubbleState(false)
        }
        let vf = currentVisibleFrame()
        let origin = clampOrigin(NSPoint(x: vf.maxX - compactSize.width - 20, y: vf.minY + 18), size: compactSize)
        panel.setFrame(NSRect(origin: origin, size: compactSize), display: true, animate: true)
        savePosition(delay: 0.4)
    }
    private func menuSection(_ title: String) -> NSMenuItem {
        if #available(macOS 14.0, *) { return NSMenuItem.sectionHeader(title: title) }
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }
    private func savePosition(delay: TimeInterval) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self, self.mode == .desktop else { return }
            let o = self.clampOrigin(self.currentPetOrigin(), size: self.compactSize)
            self.defaults.set(Double(o.x), forKey: "ro.pos.x")
            self.defaults.set(Double(o.y), forKey: "ro.pos.y")
        }
    }
    @objc private func quitApp() {
        NSApp.terminate(nil)
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let dict = message.body as? [String: Any],
              let type = dict["type"] as? String else { return }
        if type == "dragStart" {
            let fromPet = (dict["fromPet"] as? Bool) ?? true
            startNativeDrag(fromPet: fromPet)
        } else if type == "moveBy" {
            let dx = CGFloat((dict["dx"] as? NSNumber)?.doubleValue ?? 0)
            let dy = CGFloat((dict["dy"] as? NSNumber)?.doubleValue ?? 0)
            let target = NSPoint(x: panel.frame.origin.x + dx, y: panel.frame.origin.y - dy)
            panel.setFrameOrigin(clampOrigin(target, size: panel.frame.size))
        } else if type == "menu" {
            mainMenu.popUp(positioning: nil, at: NSEvent.mouseLocation, in: nil)
        } else if type == "status" {
        } else if type == "bubble" {
            let open = (dict["open"] as? Bool) ?? false
            setBubbleState(open)
        } else if type == "look" {
            for item in lookItems {
                guard let choice = item.representedObject as? [String], choice.count == 2 else { continue }
                if let value = dict[choice[0]] as? String, value == choice[1] { lookPrefs[choice[0]] = value }
            }
            for item in lookItems {
                guard let choice = item.representedObject as? [String], choice.count == 2 else { continue }
                item.state = lookPrefs[choice[0]] == choice[1] ? .on : .off
            }
        } else if type == "prefs" {
            if let material = dict["material"] as? String {
                materialName = material
                for item in matItems { item.state = (item.representedObject as? String) == material ? .on : .off }
            }
        } else if type == "hit" {
            let rects = (dict["rects"] as? [[NSNumber]])?.map { $0.map { CGFloat($0.doubleValue) } } ?? []
            hitRects = rects.filter { $0.count == 4 }.map { NSRect(x: $0[0], y: $0[1], width: $0[2], height: $0[3]) }
            hitReady = !hitRects.isEmpty
            updateClickThrough()
        } else if type == "glass" {
            let rects = (dict["rects"] as? [[NSNumber]])?.map { $0.map { $0.doubleValue } } ?? []
            updateGlass(on: (dict["on"] as? Bool) ?? false, rects: rects,
                        dark: (dict["dark"] as? Bool) ?? false, tint: dict["tint"] as? String)
        } else if type == "size" {
            if let code = dict["size"] as? String { applySize(code) }
        } else if type == "toggleWander" {
            let enabled = (dict["enabled"] as? Bool) ?? !wanderEnabled
            wanderEnabled = enabled
            wanderItem?.state = wanderEnabled ? .on : .off
            defaults.set(wanderEnabled, forKey: "ro.wander")
        }
    }
}
#if canImport(Sparkle)
extension PetAppDelegate: SPUUpdaterDelegate {
    func updater(_ updater: SPUUpdater, willInstallUpdateOnQuit item: SUAppcastItem, immediateInstallationBlock immediateInstallHandler: @escaping () -> Void) -> Bool {
        immediateInstallHandler()
        return true
    }
}
#endif
var urlArg = "http://127.0.0.1:8765/"
var wanderArg = false
let args = CommandLine.arguments
var i = 1
while i < args.count {
    if args[i] == "--url", i + 1 < args.count {
        urlArg = args[i + 1]
        i += 2
    } else if args[i] == "--wander" {
        wanderArg = true
        i += 1
    } else {
        i += 1
    }
}
let app = NSApplication.shared
let delegate = PetAppDelegate(url: urlArg, wander: wanderArg)
app.delegate = delegate
app.run()
