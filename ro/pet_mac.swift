import AppKit
import AVFoundation
import Carbon
import CoreAudio
import CoreGraphics
import Darwin
import IOKit
import ServiceManagement
import WebKit
#if canImport(Sparkle)
import Sparkle  // 앱 번들에 Sparkle이 들어간 빌드(build-app.sh)에서만. 개발용 swiftc 빌드에는 없다
#endif

// 다른 앱이 앞에 있어도 첫 클릭이 창 활성화에 쓰이고 사라지지 않게 한다
final class PetWebView: WKWebView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

final class FloatingPetPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }

    // macOS 기본 창 높이 제한(메뉴바 아래로 큰 창 상단이 막히는 현상)을 해제하고 직접 화면 경계로 클램핑한다
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        return frameRect
    }
}

// MARK: - 몸통 아래 시스템 유리
// 웹 화면은 투명 창 뒤를 볼 수 없어 CSS로는 굴절·흐림을 못 낸다. 그래서 몸통 세 층 자리에 시스템 유리를 깐다.
// macOS 26 이상: 뒤 화면을 굴절시키는 유리(NSGlassEffectView). 그보다 낮으면: 뒤 화면을 실제로 흐리는 NSVisualEffectView.
// NSGlassEffectView는 macOS 26 SDK(Swift 6.2)에만 있으므로, 예전 Xcode에서도 빌드되게 컴파일러 버전으로 감싼다.

/// 웹 화면 좌표(왼쪽 위 기준, CSS 픽셀 = 포인트)를 그대로 쓰기 위한 뒤집힌 뷰
/// 토스트 패널은 키 창이 되지 않는다(입력 중인 앱의 포커스를 뺏지 않는다). 버튼은 첫 클릭을 받는다
final class NudgePanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
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
    // 회전된 뷰의 frame은 테두리 상자다. 적용한 원본을 보관하고 뷰가 없어지면 함께 해제한다.
    private static let geometry = NSMapTable<NSView, Geometry>.weakToStrongObjects()

    /// `defaults write ro.pet ro.glass blur` 로 굴절 유리 대신 흐림 유리를 강제할 수 있다(되돌리기: defaults delete ro.pet ro.glass)
    static var forceBlur = false

    /// 창을 늘 활성 모습으로 그리게 했는지(forceActiveAppearance 성공 여부)
    static var activeForced = false

    /// 웹 화면에 알려 줄 유리 종류: "liquid"(굴절) 또는 "blur"(흐림).
    /// 굴절 유리는 창이 비활성이면 뿌옇게 그려진다(펫 창은 다른 앱을 쓰는 동안 늘 비활성이다).
    /// 창을 늘 활성 모습으로 그리게 했으면 항상 굴절 유리, 못 했으면 비활성일 때는 늘 켜 둘 수 있는 흐림 유리(state = .active)로 바꾼다.
    static func kind(active: Bool) -> String {
        #if compiler(>=6.2)
        if #available(macOS 26.0, *), !forceBlur, active || activeForced { return "liquid" }
        #endif
        return "blur"
    }

    /// 비활성 창의 굴절 유리를 활성 모습으로 그리게 하는 공개 API가 없다(NSGlassEffectView엔 state가 없음).
    /// 그래서 AppKit의 비공개 `_setForceMainAppearance:`를 쓴다. 모양만 바꾸고 키 입력·활성 상태는 바꾸지 않는다.
    /// 이 호출이 없어진 macOS에서는 응답하지 않으므로 건너뛰고, 위의 흐림 유리 대체가 그대로 동작한다.
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

    /// 알약 모양(높이의 절반 반지름)으로 frame에 맞추고, 중심을 축으로 rotation도(웹 화면의 시계 방향)만큼 돌린다.
    /// 부모가 뒤집힌 좌표(아래로 +y)라 양수 회전이 화면에서 시계 방향이 되어 CSS rotate와 같은 방향이다. dark면 연기 낀 유리
    static func shape(_ v: NSView, frame: NSRect, rotation: CGFloat, alpha: CGFloat, dark: Bool, tint: NSColor?) {
        let appearance: NSAppearance.Name = dark ? .darkAqua : .aqua
        if v.appearance?.name != appearance { v.appearance = NSAppearance(named: appearance) }
        let previous = geometry.object(forKey: v)
        let sizeChanged = previous?.frame.size != frame.size
        if previous?.frame != frame || previous?.rotation != rotation {
            v.frameCenterRotation = 0  // 돌린 채로 frame을 바꾸면 테두리 상자 기준으로 바뀐다
            v.frame = frame
            v.frameCenterRotation = rotation
            geometry.setObject(Geometry(frame: frame, rotation: rotation), forKey: v)
        }
        if v.alphaValue != alpha { v.alphaValue = alpha }
        #if compiler(>=6.2)
        if #available(macOS 26.0, *), let g = v as? NSGlassEffectView {
            if g.style != .clear { g.style = .clear }  // 뒤가 또렷이 비치고 가장자리에서 휘는 투명 유리
            if g.cornerRadius != frame.height / 2 { g.cornerRadius = frame.height / 2 }
            let color = tint?.withAlphaComponent(0.46) ?? (dark ? NSColor.black.withAlphaComponent(0.28) : nil)
            if g.tintColor != color { g.tintColor = color }
            return
        }
        #endif
        guard let e = v as? NSVisualEffectView else { return }
        // 구형 NSVisualEffectView는 몸통 tint를 지원하지 않으므로 기존 material을 유지한다.
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

// MARK: - CPU 걸음 (07). 순수 계산만 두어 --selftest로 GUI 없이 확인한다

// host_statistics(HOST_CPU_LOAD_INFO)의 누적 틱. 배열 순서는 USER, SYSTEM, IDLE, NICE (idle은 인덱스 2)
struct CPUTicks: Equatable {
    var user: UInt32
    var system: UInt32
    var idle: UInt32
    var nice: UInt32

    // 카운터는 UInt32라 몇 달 켜 두면 한 바퀴 돈다. 합과 차를 모두 &+ / &- 로 해야 wrap에도 맞는다
    var busy: UInt32 { user &+ system &+ nice }
    var total: UInt32 { busy &+ idle }

    init(user: UInt32, system: UInt32, idle: UInt32, nice: UInt32) {
        self.user = user
        self.system = system
        self.idle = idle
        self.nice = nice
    }

    // 커널이 주는 cpu_ticks 튜플을 이름 붙은 필드로. 순서를 틀리면 사용률이 100%로 나온다
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

// 두 표본 사이 전체 CPU 사용률(0~100). 틱이 안 늘었으면(잠자기 직후 등) nil
func cpuPercent(from prev: CPUTicks, to cur: CPUTicks) -> Double? {
    let total = cur.total &- prev.total
    guard total > 0 else { return nil }
    let busy = cur.busy &- prev.busy
    return min(100, Double(busy) / Double(total) * 100)
}

// 걸음 4단계. 경계는 20/50/80이고 메뉴 막대는 0.8초보다 빨라지지 않는다
enum Gait: Int, CaseIterable {
    case calm = 0, walk, busy, hot

    static let edges: [Double] = [20, 50, 80]
    var period: Double { [3.2, 1.6, 0.8, 0.4][rawValue] }
    var rate: Double { 3.2 / period }
    var menubarPeriod: Double { max(period, 0.8) }
    var label: String { ["Relaxed", "Steady", "Busy", "Overheating"][rawValue] }
    // 아이콘 점프 높이(pt)와 웅크림·늘어남 정도. 바쁨은 더 높이·더 크게 찌그러지고, 과열은 낮고 잦게
    var jumpHeight: Double { [1.0, 1.6, 2.2, 1.0][rawValue] }
    var squash: Double { [0.08, 0.12, 0.18, 0.10][rawValue] }

    // 저전력 모드에서는 '보통 걸음'까지만
    func capped(lowPower: Bool) -> Gait {
        lowPower ? Gait(rawValue: min(rawValue, Gait.walk.rawValue))! : self
    }
}

// MARK: 메뉴 막대 아이콘 점프 (07 시안: 제자리에서 콩). 프레임 3장을 f1·f2·f3·f2·f1 순서로 바꾼다

enum JumpFrame: Int {
    case crouch = 0, rise, apex  // f1 웅크림, f2 솟음, f3 정점
}

// 한 사이클 안에서 프레임을 바꾸는 시점(비율). 이륙 15%·정점 45%·착지 75%, 남은 25%는 바닥에서 숨 고르기.
// 메뉴 막대는 보간이 없으니 시안의 타임라인(0 / 480 / 720 / 960 / 1200ms @1.6초) 그대로 바꾼다
let jumpSchedule: [(at: Double, frame: JumpFrame)] = [
    (0.00, .crouch), (0.30, .rise), (0.45, .apex), (0.60, .rise), (0.75, .crouch),
]

// 아이콘 캔버스 18×18pt. 몸은 16pt 디자인 그대로 두고 위쪽 여유로 뛴다
let iconCanvas: CGFloat = 18

struct IconPose {
    var head: CGRect
    var body: CGRect
    var base: CGRect
    var narrowEyes: Bool
}

// frame이 nil이면 서 있는 기본 자세. 층은 바닥부터 쌓고, 솟을 때는 머리가 먼저 가고 받침이 늦게 따라온다
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

// 최근 3개 중앙값(순간 튐 제거) → 지수 평균 α=0.3 → 모든 경계에 ±5% 히스테리시스.
// 시뮬레이션(docs/PET-MENUBAR-MODE.md): 50% 근처 10분 140회 → 13회 전환
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
        // 한 번에 여러 단계를 건너뛸 수 있다 (5% → 90% 계단)
        while gait != .hot && value >= Gait.edges[gait.rawValue] + Self.gap {
            gait = Gait(rawValue: gait.rawValue + 1)!
        }
        while gait != .calm && value < Gait.edges[gait.rawValue - 1] - Self.gap {
            gait = Gait(rawValue: gait.rawValue - 1)!
        }
        return gait
    }

    // 잠자기·화면 꺼짐 뒤에는 이전 값이 의미 없으니 처음부터
    mutating func reset() {
        recent = []
        smoothed = nil
        gait = .calm
    }
}

// MARK: - 과열 알림 (07). "Mac이 힘들어해요"는 1분 넘게 바쁠 때 한 번만

struct RollingMean {
    let capacity: Int
    private(set) var values: [Double] = []

    init(capacity: Int) {
        self.capacity = capacity
    }

    mutating func push(_ v: Double) {
        values.append(v)
        if values.count > capacity { values.removeFirst() }
    }

    var isFull: Bool { values.count == capacity }
    var mean: Double { values.isEmpty ? 0 : values.reduce(0, +) / Double(values.count) }

    mutating func reset() {
        values = []
    }
}

// 원시 CPU의 60초 평균이 85% 이상이면 한 번 울린다. 평균이 75% 아래로 내려가야 다시 울릴 수 있다.
// (시뮬레이션: 진입/해제 규칙은 빌드처럼 잠깐씩 꺼지는 부하에서 안 울리고 평균 83%에서 울렸다)
struct OverheatGate {
    static let enter = 85.0
    static let rearm = 75.0
    private(set) var window = RollingMean(capacity: 60)
    private(set) var armed = true

    mutating func push(_ raw: Double) -> Bool {
        window.push(raw)
        if !armed {
            if window.mean < Self.rearm { armed = true }
            return false
        }
        if window.isFull && window.mean >= Self.enter {
            armed = false
            return true
        }
        return false
    }

    mutating func reset() {
        window.reset()
        armed = true
    }
}

// proc_pid_rusage의 시간은 나노초가 아니라 mach 틱이다 (Apple Silicon timebase 125/3)
func machToSeconds(_ ticks: UInt64, numer: UInt32, denom: UInt32) -> Double {
    Double(ticks) * Double(numer) / Double(denom) / 1e9
}

// 실행 파일 경로에서 가장 바깥 .app 이름. Chrome Helper 수십 개가 'Google Chrome' 하나로 묶인다
func appName(forExecutablePath path: String) -> String {
    let parts = path.split(separator: "/")
    if let app = parts.first(where: { $0.hasSuffix(".app") }) {
        return String(app.dropLast(4))
    }
    return String(parts.last ?? "")
}

// 1위 앱의 몫(%)이 읽지 못한 몫(시스템·root 프로세스)보다 클 때만 이름을 댄다. 엉뚱한 앱을 지목하지 않게
func overheatCulprit(_ usage: [String: Double], unreadable: Double) -> (name: String, share: Double)? {
    guard let top = usage.max(by: { $0.value < $1.value }), top.value > 0, top.value > unreadable else { return nil }
    return (top.key, top.value)
}

// 같은 앱은 하루 한 번, '오늘은 그만'이면 그날은 더 없다. 앱 이름이 없으면 ""로 센다
func shouldAlertOverheat(app: String?, today: String, memoDay: String?, muted: Bool, alerted: [String]) -> Bool {
    guard memoDay == today else { return true }
    if muted { return false }
    return !alerted.contains(app ?? "")
}

// MARK: - 크기(small/medium/big). 순수 계산만 두어 --selftest로 확인한다
// MARK: - 메뉴 언어. 기본은 영어, 설정(메뉴의 Language)에서 한국어로 바꾼다. 웹 화면이 저장된 값을 알려 준다
var roLang = "en"
let roKorean: [String: String] = [
    "Open panel": "열기", "Close panel": "닫기", "Command palette (⌥R)": "명령 팔레트 (⌥R)",
    "Idle": "평소", "Recording": "기록", "Focus": "집중", "Attention": "주의", "Discovery": "발견", "Resolved": "해결",
    "Expression": "표정", "Motion": "동작", "Reactions": "앱 반응",
    "Breathe": "숨쉬기", "Look around": "두리번", "Walk": "걷기", "Think": "생각", "Startle": "깜짝", "Drowsy": "꾸벅",
    "Gaze": "시선", "Press": "꾹", "Pet": "쓰다듬기", "Drag": "잡기", "Shake": "흔들기", "Land": "착지",
    "Success": "성공", "Failure": "실패", "Open": "앱 열림", "Mail": "메일", "Message": "메시지",
    "Preview expressions & motion": "표정·동작 미리보기", "Material": "재질", "Clay": "클레이", "Glass": "글래스",
    "Size": "크기", "Small": "작게", "Medium": "보통", "Big": "크게",
    "Panel color": "패널 색상", "System": "자동", "Light": "라이트", "Dark": "다크",
    "Language": "언어", "Wander": "돌아다니기", "Open at login": "로그인 시 자동 실행",
    "Bring to desktop": "데스크톱으로 꺼내기", "Send to menu bar": "메뉴 막대로 보내기",
    "Call to bottom right": "오른쪽 아래로 부르기", "Check for updates…": "업데이트 확인…", "Quit ro pet": "ro 종료",
    "Relaxed": "여유", "Steady": "보통", "Busy": "바쁨", "Overheating": "과열",
    "Loading today's records": "불러오는 중", "Measuring CPU": "CPU 측정 중",
    "Moved to the menu bar": "메뉴 막대로 옮겼어요", "Drag the icon down to bring it back": "아이콘을 아래로 끌면 다시 나와요",
    "The menu bar is full": "메뉴 막대에 자리가 없어요",
    "The icon would hide behind the notch, so ro stayed on the desktop": "아이콘이 노치에 가려져서 데스크톱에 남겨 뒀어요",
    "Your Mac is struggling": "Mac이 버거워해요", "Open Activity Monitor": "활성 상태 보기 열기", "Not today": "오늘은 그만",
    "Could not change the login setting": "로그인 설정을 바꾸지 못했어요",
    "Check System Settings › General › Login Items": "시스템 설정 › 일반 › 로그인 항목에서 확인해 주세요",
    "License…": "라이선스…", "ro pro license": "ro pro 라이선스",
    "Get pro…": "pro 받기…", "Get ro pro": "ro pro 받기", "Get my key automatically": "키 자동으로 받기",
    "Pay in your browser. When the payment goes through, ro turns pro on by itself — no key to paste.":
        "브라우저에서 결제하세요. 결제가 끝나면 ro가 알아서 pro를 켜요. 키를 붙여 넣을 필요 없어요.",
    "Yearly · $24": "연간 · $24", "Monthly · $3": "월간 · $3", "Could not start the purchase": "구매를 시작하지 못했어요",
    "Paste the key from your purchase email. It is checked on this Mac only, without the internet.":
        "구매 이메일로 받은 키를 붙여 넣으세요. 인터넷 없이 이 Mac에서만 검사해요.",
    "Save key": "키 저장", "Remove key": "키 지우기", "Cancel": "취소", "Later": "나중에",
    "Restart ro now": "지금 ro 다시 시작", "License saved": "라이선스를 저장했어요", "Key removed": "키를 지웠어요",
    "Could not save the key": "키를 저장하지 못했어요",
    "Could not reach ro. Quit and reopen the pet, then try again.": "ro에 연결하지 못했어요. 펫을 종료했다가 다시 열고 해 보세요.",
    "ro restarts to apply it. Your files and records stay as they are.": "적용하려면 ro를 다시 시작해요. 파일과 기록은 그대로예요.",
    "Remove the license key from this Mac? ro goes back to mini. Your files and records stay as they are.":
        "이 Mac에서 라이선스 키를 지울까요? ro는 mini로 돌아가고, 파일과 기록은 그대로예요.",
]
func L(_ en: String) -> String { roLang == "ko" ? (roKorean[en] ?? en) : en }

let petSizeScales: [String: CGFloat] = ["small": 0.75, "medium": 1.0, "big": 1.3]
let petBaseCompactSize = NSSize(width: 176, height: 168)

/// 말풍선을 접은 창 크기. 모르는 이름은 medium으로 본다
func petCompactSize(_ name: String) -> NSSize {
    let k = petSizeScales[name] ?? 1
    return NSSize(width: (petBaseCompactSize.width * k).rounded(), height: (petBaseCompactSize.height * k).rounded())
}

/// 크기를 바꿀 때 펫이 앉은 아래·오른쪽 모서리를 그대로 두는 새 원점
func petResizeOrigin(frame: NSRect, newSize: NSSize) -> NSPoint {
    NSPoint(x: frame.maxX - newSize.width, y: frame.minY)
}

// MARK: - 앱 반응(open/mail/message). 판정은 순수 계산으로 두어 --selftest로 확인한다
// 읽는 것은 앞에 온 앱의 번들 ID뿐이다. 창 제목·화면·키 입력은 읽지 않고, 아무것도 저장·전송·기록하지 않는다
enum ReactKind: String, CaseIterable {
    case open, mail, message
}

// 확인됨: 이 Mac의 설치본에서 번들 ID를 직접 읽었다(2026-11-10)
let reactMailAppsVerified: Set<String> = ["com.apple.mail"]
let reactMessageAppsVerified: Set<String> = [
    "com.apple.MobileSMS", "com.tinyspeck.slackmacgap", "com.kakao.KakaoTalkMac", "com.hnc.Discord",
    "com.tdesktop.Telegram",  // Telegram 데스크톱(배포판마다 ID가 다르다)
]
// 미확인: 이 Mac에 없어 공개 정보로 추정한 ID다. 틀렸다면 그 앱에서 반응이 뜨지 않을 뿐이다
let reactMailAppsUnverified: Set<String> = ["com.microsoft.Outlook", "com.readdle.smartemail-Mac"]
let reactMessageAppsUnverified: Set<String> = [
    "ru.keepcoder.Telegram",  // Telegram 앱스토어판
    "net.whatsapp.WhatsApp", "jp.naver.line.mac", "com.microsoft.teams2",
]
// 브라우저 속 웹메일은 범위 밖이다(크롬 앱 ID는 com.google.Chrome.app.<해시>라 정적 목록으로 못 잡는다)

/// 앞에 온 앱이 메일·메시지 앱이면 그 종류. 아니면 nil
func reactKind(forBundleID id: String?) -> ReactKind? {
    guard let id = id else { return nil }
    if reactMailAppsVerified.contains(id) || reactMailAppsUnverified.contains(id) { return .mail }
    if reactMessageAppsVerified.contains(id) || reactMessageAppsUnverified.contains(id) { return .message }
    return nil
}

/// 반응을 낼지 정하는 문지기. 시각은 초 단위 단조 시계(systemUptime)이고 메모리에만 둔다
struct ReactGate {
    static let mergeWindow: TimeInterval = 1.5   // 실행 알림 뒤 이 안에 같은 앱이 앞에 오면 하나로 합친다
    static let startQuiet: TimeInterval = 20     // 로그인 직후 몰리는 실행 알림
    static let wakeQuiet: TimeInterval = 10      // 잠금 해제·화면 깨어남 직후
    static func cooldown(_ kind: ReactKind) -> TimeInterval { kind == .open ? 6 : 20 }

    private(set) var lastAt: [ReactKind: TimeInterval] = [:]
    private(set) var openQuietUntil: TimeInterval

    init(startedAt: TimeInterval) { openQuietUntil = startedAt + Self.startQuiet }

    mutating func woke(at now: TimeInterval) { openQuietUntil = max(openQuietUntil, now + Self.wakeQuiet) }

    func allows(_ kind: ReactKind, at now: TimeInterval) -> Bool {
        if kind == .open, now < openQuietUntil { return false }
        if let last = lastAt[kind], now - last < Self.cooldown(kind) { return false }
        return true
    }

    /// 웹 화면이 반응을 실제로 띄웠을 때만 부른다. 거부된 반응은 쿨다운을 쓰지 않는다
    mutating func succeeded(_ kind: ReactKind, at now: TimeInterval) { lastAt[kind] = now }

    /// 앱이 앞에 왔을 때 낼 반응. 방금(mergeWindow 안) 실행된 앱이면 기다리던 open을 취소하고 mail·message > open 하나만 낸다
    static func onActivate(kind: ReactKind?, sinceLaunch: TimeInterval?) -> (emit: ReactKind?, cancelsPendingOpen: Bool) {
        if let since = sinceLaunch, since < mergeWindow { return (kind ?? .open, true) }
        return (kind, false)
    }

    /// 앱 실행 알림을 받았을 때. 실제 macOS에서는 새로 뜬 앱의 "앞에 옴" 알림이 실행 알림보다 먼저 오기도 한다.
    /// 이미 앞에 와 있으면 메일·메시지 앱은 그 활성화가 반응을 냈으므로 더 내지 않고, 보통 앱만 지금 open을 낸다.
    /// 아직 앞에 오지 않았으면 mergeWindow만큼 활성화를 기다린다
    static func onLaunch(kind: ReactKind?, alreadyActive: Bool) -> (emit: ReactKind?, waitsForActivation: Bool) {
        if alreadyActive { return (kind == nil ? .open : nil, false) }
        return (nil, true)
    }
}

// 창을 띄우지 않고 계산과 유리 갱신을 확인한다. 실패 항목을 출력하고 실패 수를 돌려준다
func runCPUSelfTest() -> Int {
    var failures = 0
    func check(_ ok: Bool, _ name: String) {
        print("\(ok ? "ok  " : "FAIL") \(name)")
        if !ok { failures += 1 }
    }
    func feed(_ values: [Double]) -> [Gait] {
        var s = CPUSmoother()
        return values.map { s.push($0) }
    }
    func switches(_ gaits: [Gait]) -> Int {
        zip(gaits, gaits.dropFirst()).filter { $0 != $1 }.count
    }

    // 커널 순서 (USER, SYSTEM, IDLE, NICE) 그대로 넣는다
    let a = CPUTicks(machTicks: (100, 100, 700, 0))
    let b = CPUTicks(machTicks: (110, 110, 780, 0))
    check(cpuPercent(from: a, to: b) == 20, "idle은 인덱스 2: 바쁨 20틱 / 전체 100틱 = 20%")

    // 카운터 셋이 함께 한 바퀴 돌아도 (합에서도 넘친다) 차이는 맞아야 한다
    let nearMax = CPUTicks(user: UInt32.max - 5, system: UInt32.max - 3, idle: UInt32.max - 50, nice: 0)
    let wrapped = CPUTicks(user: 4, system: 6, idle: 29, nice: 0)  // user +10, system +10, idle +80
    let wrapPct = cpuPercent(from: nearMax, to: wrapped) ?? -1
    check(abs(wrapPct - 20) < 0.01, "UInt32 wrap에도 사용률이 맞다 (\(String(format: "%.2f", wrapPct)))")
    check(cpuPercent(from: a, to: a) == nil, "틱이 안 늘면 nil")

    var spikes = Array(repeating: 6.0, count: 60)
    spikes[20] = 76
    spikes[41] = 76
    check(feed(spikes).allSatisfy { $0 == .calm }, "한가할 때 순간 튐 한 번은 무시한다")

    let hover = (0..<240).map { $0 % 2 == 0 ? 44.0 : 56.0 }
    check(switches(feed(hover)) <= 1, "50% 근처에서 단계가 흔들리지 않는다")

    let step = Array(repeating: 5.0, count: 30) + Array(repeating: 90.0, count: 30)
    let stepGaits = feed(step)
    let hotAt = stepGaits.firstIndex(of: .hot).map { $0 - 30 } ?? -1
    check(hotAt >= 0 && hotAt <= 10, "5% → 90% 계단은 10초 안에 과열 (\(hotAt)초)")

    var s = CPUSmoother()
    for _ in 0..<30 { _ = s.push(95) }
    for _ in 0..<30 { _ = s.push(78) }
    check(s.gait == .hot, "과열은 75% 아래로 내려가야 풀린다 (78%는 유지)")
    for _ in 0..<30 { _ = s.push(70) }
    check(s.gait == .busy, "70%면 바쁨으로 내려온다")

    check(Gait.allCases.map(\.period) == [3.2, 1.6, 0.8, 0.4], "사이클 3.2 / 1.6 / 0.8 / 0.4초")
    check(Gait.hot.menubarPeriod == 0.8 && Gait.calm.menubarPeriod == 3.2, "메뉴 막대는 0.8초 상한")
    check(Gait.hot.capped(lowPower: true) == .walk && Gait.busy.capped(lowPower: false) == .busy
          && Gait.calm.capped(lowPower: true) == .calm, "저전력은 '보통 걸음'까지")
    check(jumpSchedule.map(\.frame) == [.crouch, .rise, .apex, .rise, .crouch]
          && jumpSchedule.first?.at == 0 && jumpSchedule.last?.at == 0.75, "f1 → f2 → f3 → f2 → f1, 착지 75%")
    check(zip(jumpSchedule, jumpSchedule.dropFirst()).allSatisfy { $0.at < $1.at }, "프레임 시점이 앞으로만 간다")
    let canvas = CGRect(x: 0, y: 0, width: iconCanvas, height: iconCanvas)
    let inside = Gait.allCases.allSatisfy { g in
        ([nil] + [JumpFrame.crouch, .rise, .apex]).allSatisfy { f in
            let p = iconPose(f, gait: g)
            return [p.head, p.body, p.base].allSatisfy { canvas.contains($0) }
        }
    }
    check(inside, "모든 단계·프레임이 18pt 캔버스 안에 있다")
    let apexTop = { (g: Gait) in iconPose(.apex, gait: g).head.minY }
    check(apexTop(.busy) < apexTop(.walk) && apexTop(.walk) < apexTop(.calm), "바쁠수록 더 높이 뛴다")
    check(apexTop(.hot) > apexTop(.busy), "과열은 낮게 뛴다")
    let crouch = iconPose(.crouch, gait: .walk), stand = iconPose(nil, gait: .walk)
    check(crouch.base.width > stand.base.width && crouch.head.minY > stand.head.minY, "웅크리면 낮고 넓어진다")
    let rise = iconPose(.rise, gait: .walk)
    check(stand.base.minY - rise.base.minY < stand.head.minY - rise.head.minY, "솟을 때 받침이 머리보다 늦게 따라온다")
    check(iconPose(.apex, gait: .hot).narrowEyes && !iconPose(.apex, gait: .busy).narrowEyes, "과열만 눈을 가늘게")

    func fires(_ values: [Double]) -> [Int] {
        var g = OverheatGate()
        return values.enumerated().compactMap { g.push($0.element) ? $0.offset : nil }
    }
    check(fires(Array(repeating: 95, count: 120)) == [59], "95%가 60초 이어지면 60초째에 한 번만")
    check(fires(Array(repeating: 95, count: 70) + Array(repeating: 60, count: 70) + Array(repeating: 95, count: 70)).count == 2,
          "평균이 75% 아래로 내려간 뒤에만 다시 울린다")
    check(fires((0..<300).map { _ in 83.0 }).isEmpty, "평균 83%로 오래 바빠도 울리지 않는다")
    let build = (0..<200).map { $0 % 40 < 34 ? 92.0 : 60.0 }  // 링크 때마다 6초씩 60%로 꺼짐 → 평균 87%
    check(!fires(build).isEmpty, "빌드처럼 잠깐씩 꺼지는 부하도 평균이 85% 넘으면 울린다")
    check(machToSeconds(24_000_000, numer: 125, denom: 3) == 1.0, "mach 틱을 timebase로 초로 바꾼다")
    let helper = "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/1/Helpers/Google Chrome Helper (Renderer).app/Contents/MacOS/Google Chrome Helper (Renderer)"
    check(appName(forExecutablePath: helper) == "Google Chrome", "Chrome Helper는 Google Chrome으로 묶는다")
    check(appName(forExecutablePath: "/usr/sbin/mds_stores") == "mds_stores", ".app 밖이면 실행 파일 이름")
    check(overheatCulprit(["Chrome": 40, "Xcode": 10], unreadable: 30)?.name == "Chrome", "1위가 읽지 못한 몫보다 크면 이름을 댄다")
    check(overheatCulprit(["Chrome": 40, "Xcode": 10], unreadable: 50) == nil, "읽지 못한 몫이 더 크면 이름 없이")
    check(shouldAlertOverheat(app: "Chrome", today: "d2", memoDay: "d1", muted: true, alerted: ["Chrome"]), "날이 바뀌면 다시 알린다")
    check(!shouldAlertOverheat(app: "Xcode", today: "d1", memoDay: "d1", muted: true, alerted: []), "'오늘은 그만'이면 그날은 없다")
    check(!shouldAlertOverheat(app: "Chrome", today: "d1", memoDay: "d1", muted: false, alerted: ["Chrome"]), "같은 앱은 하루 한 번")
    check(shouldAlertOverheat(app: "Xcode", today: "d1", memoDay: "d1", muted: false, alerted: ["Chrome"]), "다른 앱은 알린다")
    class GlassProbe: NSVisualEffectView {
        var writes = 0
        override var frame: NSRect { didSet { writes += 1 } }
        override var frameCenterRotation: CGFloat { didSet { writes += 1 } }
        override var appearance: NSAppearance? { didSet { writes += 1 } }
        override var alphaValue: CGFloat { didSet { writes += 1 } }
        override var material: NSVisualEffectView.Material { didSet { writes += 1 } }
        override var maskImage: NSImage? { didSet { writes += 1 } }
    }
    let glass = GlassProbe()
    var glassFrame = NSRect(x: 10, y: 20, width: 80, height: 20)
    func shapeGlass(_ rotation: CGFloat = 15, dark: Bool = false, alpha: CGFloat = 0.8) {
        NativeGlass.shape(glass, frame: glassFrame, rotation: rotation, alpha: alpha, dark: dark, tint: nil)
    }
    shapeGlass()
    let mask = glass.maskImage
    glass.writes = 0
    shapeGlass()
    check(glass.writes == 0, "회전된 동일 자세에서는 유리 속성을 재설정하지 않는다")
    glassFrame.origin.x += 5
    shapeGlass()
    check(glass.writes > 0 && glass.maskImage === mask, "유리 위치만 바꾸면 마스크를 재사용한다")
    glass.writes = 0
    shapeGlass(25)
    check(glass.writes > 0 && glass.frameCenterRotation == 25 && glass.maskImage === mask, "유리 회전만 바뀌어도 적용한다")
    glass.writes = 0
    shapeGlass(25)
    check(glass.writes == 0, "새 회전도 반복 적용하지 않는다")
    shapeGlass(25, dark: true, alpha: 0.6)
    check(glass.appearance?.name == .darkAqua && glass.alphaValue == 0.6 && glass.material == .hudWindow,
          "유리 외관과 투명도 변경은 반영한다")
    glassFrame.size.height += 2
    shapeGlass(25, dark: true, alpha: 0.6)
    check(glass.maskImage !== mask && glass.maskImage?.size == glassFrame.size, "유리 크기가 바뀌면 마스크를 갱신한다")
    check(petCompactSize("small") == NSSize(width: 132, height: 126), "small 창은 132×126")
    check(petCompactSize("medium") == NSSize(width: 176, height: 168), "medium 창은 기존 176×168 그대로")
    check(petCompactSize("big") == NSSize(width: 229, height: 218), "big 창은 229×218")
    check(petCompactSize("huge") == petCompactSize("medium"), "모르는 크기 이름은 medium")
    let before = NSRect(x: 1000, y: 40, width: 176, height: 168)
    for name in ["small", "big"] {
        let size = petCompactSize(name)
        let after = NSRect(origin: petResizeOrigin(frame: before, newSize: size), size: size)
        check(after.maxX == before.maxX && after.minY == before.minY, "\(name)로 바꿔도 아래·오른쪽 모서리는 그대로")
    }
    check(reactKind(forBundleID: "com.apple.mail") == .mail && reactKind(forBundleID: "com.apple.MobileSMS") == .message,
          "메일·메시지 앱의 번들 ID를 종류로 판정한다")
    check(reactKind(forBundleID: "com.tdesktop.Telegram") == .message && reactKind(forBundleID: "ru.keepcoder.Telegram") == .message,
          "Telegram은 데스크톱판·앱스토어판 모두 메시지")
    check(reactKind(forBundleID: "com.apple.finder") == nil && reactKind(forBundleID: nil) == nil
          && reactKind(forBundleID: "com.google.Chrome.app.gmail") == nil, "그 밖의 앱과 없는 ID는 반응 종류가 없다")
    check(reactMailAppsVerified.union(reactMessageAppsVerified).isDisjoint(with: reactMailAppsUnverified.union(reactMessageAppsUnverified)),
          "확인된 ID와 미확인 ID는 겹치지 않는다")
    var gate = ReactGate(startedAt: 100)
    check(gate.allows(.mail, at: 101) && gate.allows(.mail, at: 101.5), "거부된(성공을 알리지 않은) 반응은 쿨다운을 쓰지 않는다")
    gate.succeeded(.mail, at: 101)
    check(!gate.allows(.mail, at: 120.9) && gate.allows(.mail, at: 121), "성공한 mail은 20초 동안 다시 내지 않는다")
    check(gate.allows(.message, at: 102), "쿨다운은 종류마다 따로다")
    check(!gate.allows(.open, at: 119.9) && gate.allows(.open, at: 120), "시작 후 20초 동안 open을 무시한다")
    gate.succeeded(.open, at: 120)
    check(!gate.allows(.open, at: 125.9) && gate.allows(.open, at: 126), "open 쿨다운은 6초")
    gate.woke(at: 200)
    check(!gate.allows(.open, at: 209.9) && gate.allows(.open, at: 210) && gate.allows(.mail, at: 201),
          "잠금 해제·깨어남 뒤 10초는 open만 무시한다")
    check(ReactGate.onActivate(kind: .mail, sinceLaunch: 0.4) == (.mail, true), "실행 직후 앞에 온 메일 앱은 open 대신 mail 하나만")
    check(ReactGate.onActivate(kind: nil, sinceLaunch: 0.4) == (.open, true), "실행 직후 앞에 온 보통 앱은 open 하나만")
    check(ReactGate.onActivate(kind: .message, sinceLaunch: 1.5) == (.message, false), "1.5초가 지나면 합치지 않는다")
    check(ReactGate.onActivate(kind: nil, sinceLaunch: nil) == (nil, false), "보통 앱으로 옮겨 가는 것만으로는 반응하지 않는다")
    check(ReactGate.onLaunch(kind: .mail, alreadyActive: true) == (nil, false), "앞에 온 뒤에 실행 알림이 온 메일 앱은 open을 덧붙이지 않는다")
    check(ReactGate.onLaunch(kind: nil, alreadyActive: true) == (.open, false), "앞에 온 뒤에 실행 알림이 온 보통 앱은 바로 open")
    check(ReactGate.onLaunch(kind: .mail, alreadyActive: false) == (nil, true), "아직 앞에 오지 않은 앱은 활성화를 기다린다")
    var idle = IdleTracker()
    check(idle.shouldSend(seconds: 0.5, now: 0), "처음 유휴 값은 보낸다")
    check(idle.shouldSend(seconds: 1.0, now: 5), "입력 중이면 매번 보낸다(파이썬이 외삽하지 않게)")
    check(idle.shouldSend(seconds: 6.0, now: 10), "입력이 멈춰 구간이 바뀌면 보낸다")
    check(!idle.shouldSend(seconds: 11.0, now: 15), "같은 구간(활동 중)이면 heartbeat 전까지 보내지 않는다")
    check(idle.shouldSend(seconds: 26.0, now: 30), "15초 heartbeat가 지나면 보낸다")
    print(failures == 0 ? "selftest passed" : "selftest failed: \(failures)")
    return failures
}

// 데스크톱 펫과 메뉴 막대 아이콘은 같은 Ro다. 한 번에 한 곳에만 보인다
enum PetMode: String {
    case desktop
    case menubar
}

final class PetAppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    private var panel: FloatingPetPanel!
    private var webView: WKWebView!
    private var glassLayer: FlippedView!   // 웹 화면 아래, 몸통 자리에 시스템 유리를 까는 층
    private var glassViews: [NSView] = []
    private var glassViewsKind = ""        // glassViews가 어느 유리로 만들어졌는지("liquid"/"blur")
    private var glassKind: String { NativeGlass.kind(active: panel.isKeyWindow) }
    private var statusItem: NSStatusItem!
    private var wanderItem: NSMenuItem!
    private var modeItem: NSMenuItem!
    private var mainMenu: NSMenu!
    // 번들 없는 swiftc 실행 파일이라 .standard 도메인이 실행 파일 이름에 묶이므로 suite를 고정한다
    private let defaults = UserDefaults(suiteName: "ro.pet") ?? .standard
    private var mode: PetMode = .desktop
    private var urlString: String = "http://127.0.0.1:8765/"
    private var wanderEnabled: Bool = false
#if canImport(Sparkle)
    // 자동 업데이트: Info.plist의 SUFeedURL이 있을 때만 켠다. 확인은 하루 한 번 appcast.xml을 읽을 뿐이고 사용자 데이터는 보내지 않는다
    private var updaterController: SPUStandardUpdaterController?
#endif
    var miniEdition = false  // V1 꾸미기 에디션: 명령 팔레트·⌥R·기록 숫자를 두지 않는다
    var proSensor = false    // ro pro: 표준출력으로 센서를 보내고 표준입력으로 토스트 명령을 받는다
    var noKill = false       // 격리 실행 시 기존 ro-pet-host를 종료하지 않는다
    private var lookPrefs = ["panel": "auto", "lang": "en"]
    private var pointerInside = false
    private var originBeforeOpen: NSPoint?  // 패널이 화면에 맞추느라 펫을 밀었을 때 닫으면 돌아갈 자리
    private var lookItems: [NSMenuItem] = []
    private var bubbleOpen: Bool = false
    private var placeTop: Bool = false
    private var placeLeft: Bool = false
    private var wanderDirection: CGFloat = -1.0
    private var wanderTimer: Timer?
    private var dragTimer: Timer?
    private var fallTimer: Timer?
    private var isDragging: Bool = false
    private var hotKeyRef: EventHotKeyRef? = nil

    // 말풍선이 닫혀 있을 때는 캐릭터(23u×22u)+캡션+그림자+점프/흔들기 여유 공간(176x168)을 확보해 잘림 방지
    // 크기(small/medium/big)는 이 창과 웹 화면의 --pet-scale을 같은 배율로 바꾼다. 상태창(말풍선)은 키우지 않는다
    private var sizeName = "medium"
    private var sizeItems: [NSMenuItem] = []
    // 앱 반응: 종류별 켜기(ro.react.<kind>)와 전체 스위치(ro.react.enabled). 기본은 모두 켬. 쿨다운 시각은 메모리에만 둔다
    private var reactEnabled = true
    private var reactKinds: Set<ReactKind> = Set(ReactKind.allCases)
    private var reactItems: [NSMenuItem] = []
    private var reactGate = ReactGate(startedAt: ProcessInfo.processInfo.systemUptime)
    private var recentLaunches: [pid_t: TimeInterval] = [:]
    private var pendingOpens: [pid_t: DispatchWorkItem] = [:]
    private var compactSize: NSSize { petCompactSize(sizeName) }
    private let edgeMargin: CGFloat = 6.0
    // 화면 위 이 거리 안으로 끌고 오면 메뉴 막대에 Ro 자리가 열린다
    private let dockZone: CGFloat = 80.0
    private var toastPanel: NSPanel?
    // 아이콘을 이만큼 아래로 끌면 펫으로 꺼낸다
    private let popOutDistance: CGFloat = 24.0
    private var iconTimer: Timer?
    private var headerTitle: NSTextField!
    private var headerDetail: NSTextField!
    // 메뉴 막대 모드에서 패널을 아이콘 아래로 옮기기 전 데스크톱 자리
    private var savedDesktopOrigin: NSPoint?
    private var cpuTimer: Timer?
    private var lastTicks: CPUTicks?
    private var smoother = CPUSmoother()
    private(set) var gait: Gait = .calm
    private var iconJumpTimer: Timer?
    private var jumpStep = 0
    private var iconGait: Gait = .calm  // 지금 아이콘이 뛰고 있는 단계. 착지(f1)할 때만 gait를 따라간다
    private var iconImages: [Int: NSImage] = [:]
    private var overheatGate = OverheatGate()
    private var overheatScanning = false
    private var alertPanel: NSPanel?
    private var talkItem: NSMenuItem!
    private var loginItem: NSMenuItem?
    private var matItems: [NSMenuItem] = []
    private var materialName = ""         // 웹 화면이 알려 준 지금 재질(메뉴 체크용)
    private var lastToday: Int?
    private var hitRects: [NSRect] = []   // 웹 화면이 알려 준 '누를 수 있는 자리'(몸통·상태창). 그 밖의 투명 여백은 클릭을 아래 앱으로 흘려보낸다
    private var hitReady = false
    private var previewHide: DispatchWorkItem?  // 메뉴 막대 모드에서 미리보기로 잠깐 꺼낸 펫을 다시 넣는 예약

    init(url: String, wander: Bool) {
        self.urlString = url
        self.wanderEnabled = wander
        super.init()
    }

    // 다른 앱이 앞에 있으면 웹 화면에 마우스 이동이 오지 않는다. 쓰다듬기·시선은 여기서 넘긴 좌표로 동작한다
    private func setupPointerWatch() {
        panel.acceptsMouseMovedEvents = true
        // 끌기 중에도 받는다: 파일을 끌고 와 펫 위에 올릴 때 클릭 통과를 풀어야 놓을 수 있다
        NSEvent.addGlobalMonitorForEvents(matching: [.mouseMoved, .leftMouseDragged]) { [weak self] _ in self?.forwardPointer() }
        // 꾸미기(mini)는 상태창이 키 창이 아니라 '포커스를 잃으면 닫기'가 오지 않는다. 다른 곳을 누르면 여기서 닫는다
        NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            guard let self = self, self.miniEdition, self.bubbleOpen else { return }
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
        if !noKill { killOtherInstances() }
        NSApp.setActivationPolicy(.accessory)
        mode = PetMode(rawValue: defaults.string(forKey: "ro.mode") ?? "") ?? .desktop
        if let saved = defaults.string(forKey: "ro.size"), petSizeScales[saved] != nil { sizeName = saved }
        if defaults.object(forKey: "ro.react.enabled") != nil { reactEnabled = defaults.bool(forKey: "ro.react.enabled") }
        for kind in ReactKind.allCases where defaults.object(forKey: "ro.react.\(kind.rawValue)") != nil {
            if !defaults.bool(forKey: "ro.react.\(kind.rawValue)") { reactKinds.remove(kind) }
        }
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
        ensureIconVisible(announceSuccess: false)  // 지난번 메뉴 막대 모드로 시작했는데 아이콘이 가려진 경우
        setupWanderTimer()
        setupCPUSampler()
        observeIconConditions()
        observeAppReactions()
        if !miniEdition { setupGlobalHotKey() }
        if proSensor {
            ProSensor.shared.onCommand = { [weak self] cmd in self?.handleProCommand(cmd) }
            ProSensor.shared.start()
        }
    }

    /// ro pro 표준입력 명령. 모르는 명령은 버린다
    private func handleProCommand(_ cmd: [String: Any]) {
        switch cmd["cmd"] as? String {
        case "ping":
            ProSensor.shared.emit(["type": "pong"])
        case "toast":
            guard let id = cmd["id"] as? String, let trigger = cmd["trigger"] as? String,
                  let text = cmd["text"] as? String, let verb = cmd["verb"] as? String else { return }
            showNudge(id: id, trigger: trigger, text: text, verb: verb, off: cmd["off"] as? String ?? "Turn off this type")
        case "palette":   // 사용자가 토스트의 '파일 찾기'를 누른 뒤에만 온다
            openPalette()
        default:
            break
        }
    }

    // MARK: 2단계 토스트 — 포커스를 뺏지 않는다(nonactivatingPanel + orderFrontRegardless, makeKey 금지)
    // 사실 한 줄 + 동사 버튼 + [이 유형 끄기]. 8초 뒤 저절로 닫히면 '무시'로 알린다. 떠 있을 때 ⌥R은 카드로 승격한다
    private var nudgePanel: NSPanel?
    private var nudgeInfo: (id: String, trigger: String)?
    private var nudgeExpiry: DispatchWorkItem?
    static let nudgeSeconds = 8.0

    private func showNudge(id: String, trigger: String, text: String, verb: String, off: String) {
        closeNudge("ignored")   // 한 번에 하나만
        let label = NSTextField(labelWithString: text)
        label.font = NSFont.systemFont(ofSize: 13)
        label.lineBreakMode = .byTruncatingTail
        label.maximumNumberOfLines = 1
        let go = NSButton(title: verb, target: self, action: #selector(nudgeAccept))
        go.bezelStyle = .rounded
        go.bezelColor = NSColor(name: nil) { a in   // 먹(어두운 면에서는 크림). 주황은 쓰지 않는다
            a.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor(srgbRed: 0.96, green: 0.95, blue: 0.92, alpha: 1)
                                                               : NSColor(srgbRed: 0.10, green: 0.10, blue: 0.09, alpha: 1)
        }
        let mute = NSButton(title: off, target: self, action: #selector(nudgeOff))
        mute.isBordered = false
        mute.font = NSFont.systemFont(ofSize: 11)
        mute.contentTintColor = .secondaryLabelColor
        for v in [label, go, mute] { v.sizeToFit() }
        let pad: CGFloat = 14, gap: CGFloat = 10
        label.frame.size.width = min(label.frame.width, 340)
        let height = max(label.frame.height, go.frame.height) + 16
        let width = pad + label.frame.width + gap + go.frame.width + 4 + mute.frame.width + pad
        let box = NSVisualEffectView(frame: NSRect(x: 0, y: 0, width: width, height: height))
        box.material = .popover
        box.state = .active
        box.wantsLayer = true
        box.layer?.cornerRadius = 12
        var x = pad
        for v in [label, go, mute] as [NSView] {
            v.frame.origin = NSPoint(x: x, y: (height - v.frame.height) / 2)
            box.addSubview(v)
            x += v.frame.width + (v === label ? gap : 4)
        }
        let vf = (statusItem.button?.window?.screen ?? NSScreen.main)?.visibleFrame ?? .zero
        let anchorX = statusItem.isVisible ? (statusItem.button?.window?.frame.midX ?? vf.midX) : vf.midX
        let originX = min(max(anchorX - width / 2, vf.minX + 8), vf.maxX - width - 8)
        let toast = NudgePanel(contentRect: NSRect(x: originX, y: vf.maxY - height - 8, width: width, height: height),
                               styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        toast.isOpaque = false
        toast.backgroundColor = .clear
        toast.hasShadow = true
        toast.level = .statusBar
        toast.hidesOnDeactivate = false
        toast.becomesKeyOnlyIfNeeded = true
        toast.collectionBehavior = [.canJoinAllSpaces, .stationary, .transient]
        toast.contentView = box
        toast.orderFrontRegardless()
        nudgePanel = toast
        nudgeInfo = (id, trigger)
        let expiry = DispatchWorkItem { [weak self] in self?.closeNudge("ignored") }
        nudgeExpiry = expiry
        DispatchQueue.main.asyncAfter(deadline: .now() + PetAppDelegate.nudgeSeconds, execute: expiry)
    }

    /// 결과를 한 번만 알리고 닫는다. 떠 있는 토스트가 없으면 false
    @discardableResult
    private func closeNudge(_ action: String) -> Bool {
        guard let info = nudgeInfo else { return false }
        nudgeInfo = nil
        nudgeExpiry?.cancel()
        nudgeExpiry = nil
        nudgePanel?.orderOut(nil)
        nudgePanel = nil
        ProSensor.shared.emit(["type": "toast_result", "id": info.id, "trigger": info.trigger, "action": action])
        return true
    }

    fileprivate func promoteNudge() { closeNudge("promote") }
    @objc private func nudgeAccept() { closeNudge("accepted") }
    @objc private func nudgeOff() { closeNudge("off") }

    /// 어느 앱에서든 ⌥R로 명령 팔레트를 연다(Carbon 핫키: 접근성 권한 불필요).
    private func setupGlobalHotKey() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let me = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, _, userData in
            guard let userData = userData else { return noErr }
            let delegate = Unmanaged<PetAppDelegate>.fromOpaque(userData).takeUnretainedValue()
            DispatchQueue.main.async {
                if delegate.proSensor { delegate.promoteNudge() }   // 토스트가 떠 있으면 카드로 승격(결과 알림)
                delegate.openPalette()
            }
            return noErr
        }, 1, &spec, me, nil)
        let id = EventHotKeyID(signature: OSType(0x726f6274), id: 1)
        RegisterEventHotKey(UInt32(kVK_ANSI_R), UInt32(optionKey), id, GetApplicationEventTarget(), 0, &hotKeyRef)
    }

    @objc private func openPalette() {
        if mode == .menubar && !bubbleOpen {
            savedDesktopOrigin = savedDesktopOrigin ?? panel.frame.origin
            panel.setFrameOrigin(menubarAnchorOrigin())
        }
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        webView.evaluateJavaScript("window.openPaletteFromHost && window.openPaletteFromHost();", completionHandler: nil)
    }

    // 중복 실행 방지: 현재 프로세스 외에 다른 ro-pet-host가 떠 있으면 즉시 종료시킨다
    private func killOtherInstances() {
        let myPid = ProcessInfo.processInfo.processIdentifier
        for app in NSWorkspace.shared.runningApplications {
            // 번들 앱(ro.app)은 localizedName이 "ro"다. 실행 파일 이름으로 가린다
            if app.processIdentifier != myPid,
               app.executableURL?.lastPathComponent == "ro-pet-host" {
                app.forceTerminate()
            }
        }
    }

    /// 상태창을 앞에 보인다. 꾸미기(mini)는 글자를 칠 곳이 없으니 쓰던 앱의 포커스를 가져가지 않는다
    private func bringPanelForward() {
        if miniEdition {
            panel.orderFrontRegardless()
        } else {
            NSApp.activate(ignoringOtherApps: true)
            panel.makeKeyAndOrderFront(nil)
        }
    }

    /// 투명 여백(몸통·상태창 밖)에서는 클릭을 아래 앱으로 흘려보낸다. 웹 화면이 자리를 알려 주기 전에는 건드리지 않는다
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

    // 화면 상하좌우 경계 클램핑: 밑으로 내릴 때 화면/Dock 아래로 사라지지 않고, 위로 올릴 때 메뉴바 바로 아래까지 이동
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

    // 현재 패널 프레임에서 펫 캐릭터(144x132)의 화면 좌표를 계산
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
        talkItem?.title = L(open ? "Close panel" : "Open panel")

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

    // 네이티브 120fps 마우스 드래그 추적 (이동 중에도 배경 밝기를 실시간 감지해 분필/먹 자동 전환)
    private func startNativeDrag(fromPet: Bool) {
        dragTimer?.invalidate()
        let startMouse = NSEvent.mouseLocation
        let startOrigin = panel.frame.origin
        var moved = false
        var tick = 0
        // 메뉴 막대로 보내기는 데스크톱 펫(말풍선 닫힘)을 끌 때만
        let canDock = fromPet && mode == .desktop && !bubbleOpen
        var inZone = false
        var lastProgress: CGFloat = 0
        isDragging = true

        if fromPet {
            // 누르는 순간 light 햅틱 1회 (트랙패드가 있는 맥에서만 느껴진다)
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
                self.originBeforeOpen = nil  // 직접 옮겼다면 옮긴 자리가 새 자리다
            }
            if moved {
                let target = NSPoint(x: startOrigin.x + dx, y: startOrigin.y + dy)
                let clamped = self.clampOrigin(target, size: self.panel.frame.size)
                self.panel.setFrameOrigin(clamped)
                // 모션 엔진에 머리(창)의 위치를 스트리밍한다(약 60Hz). 속도·체인·기울기·흔들기 감지는 JS가 계산한다.
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
                    self.statusItem.isVisible = nowIn  // 막대에 자리를 열고 닫는다
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
                if moved && self.mode == .desktop { self.savePosition(delay: 0.5) }  // 낙하가 끝난 자리
                if fromPet {
                    // 놓으면 중력(2400px/s²)으로 조금 떨어진다. 놓은 자리에서 멀어지지 않게 최대 24px
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

    /// 바닥(작업 영역 아래 여백) 쪽으로 조금 떨어진다. 반환: 실제로 떨어진 거리(px). 최대 24px(≈94px).
    private func startFall() -> CGFloat {
        let g: CGFloat = 2400
        let maxFall: CGFloat = 24  // 놓은 자리에서 크게 떨어지지 않는다(약 141ms)
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

    // 놓는 순간 펫 창을 아이콘 자리로 빨아들이고 숨긴다. 다시 꺼내면 끌기 전 자리로 돌아온다
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
            // 아이템이 많으면 노치 뒤로 숨는다. 가려졌으면 알리고 데스크톱으로 되돌린다
            self.ensureIconVisible(announceSuccess: true)
        })
    }

    // 아이템이 많으면 아이콘이 노치 뒤로 숨는다. 가려졌으면 알리고 데스크톱으로 되돌린다.
    // 전체 화면 앱 때문에 메뉴 막대가 숨은 경우는 가려진 것으로 보지 않는다
    private func ensureIconVisible(announceSuccess: Bool) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            guard let self = self, self.mode == .menubar,
                  let win = self.statusItem.button?.window else { return }
            if win.occlusionState.contains(.visible) {
                if announceSuccess {
                    self.showToast(L("Moved to the menu bar"), L("Drag the icon down to bring it back"))
                }
            } else if NSMenu.menuBarVisible() {
                self.setMode(.desktop)
                self.showToast(L("The menu bar is full"), L("The icon would hide behind the notch, so ro stayed on the desktop"))
            }
        }
    }

    // 착지 바운스 1회: 살짝 올라간 아이콘을 잠깐 보여 준 뒤 제자리로
    private func bounceIcon() {
        guard let btn = statusItem.button else { return }
        btn.image = makeIcon(iconPose(.apex, gait: .walk))
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { [weak self] in
            self?.statusItem.button?.image = self?.makeIcon(iconPose(nil, gait: .calm))
        }
    }

    // 펫 창이 숨은 상태에서도 보이도록 메뉴 막대 아래에 잠깐 띄우는 알림
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
        toast.collectionBehavior = [.canJoinAllSpaces, .stationary, .transient]
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
            // 기기 픽셀에 맞춘다. 안 맞추면 1x 화면에서 0.8pt 층 사이와 1.3pt 눈이 회색으로 번진다 (9단계 확인).
            // 위치와 크기를 따로 반올림해 두 눈 크기가 같게, 층은 받침부터 쌓아 층 사이가 1px 아래로 붙지 않게 한다
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
            // 템플릿 이미지는 알파만 쓰므로 눈은 색을 칠하지 않고 투명하게 뚫는다. 과열이면 가늘게 뜬다
            let hd = head
            let eyes = pose.narrowEyes
                ? [NSRect(x: hd.minX + 5.3, y: hd.minY + hd.height * 0.42, width: 1.7, height: 1.0),
                   NSRect(x: hd.minX + 7.9, y: hd.minY + hd.height * 0.42, width: 1.5, height: 1.0)]
                : [NSRect(x: hd.minX + 5.5, y: hd.minY + hd.height * 0.24, width: 1.3, height: hd.height * 0.5),
                   NSRect(x: hd.minX + 8.0, y: hd.minY + hd.height * 0.28, width: 1.2, height: hd.height * 0.42)]
            NSGraphicsContext.current?.compositingOperation = .clear
            // 눈은 크기를 먼저 반올림하고 원래 중심에 다시 놓는다 (두 눈 높이가 어긋나 보이지 않게)
            func snapEye(_ e: NSRect) -> NSRect {
                // 높이는 내림: 1x에서 2.5pt·2.1pt 눈이 3px·2px로 갈려 한쪽이 들려 보이던 것을 막는다 (2x는 5px·4px 유지)
                let w = max(1 / px, round(e.width)), h = max(1 / px, (e.height * px).rounded(.down) / px)
                return NSRect(x: round(e.midX - w / 2), y: round(e.midY - h / 2), width: w, height: h)
            }
            for e in eyes.map(snapEye) {
                NSBezierPath(roundedRect: e, xRadius: 0.5, yRadius: 0.5).fill()
            }
            NSGraphicsContext.current?.compositingOperation = .sourceOver
            return true
        }
        img.isTemplate = true  // 다크 메뉴바에서는 시스템이 흰색으로 바꿔 그린다
        return img
    }

    private let statusAutosaveName = "ro.pet"

    /// 메뉴 막대로 보낸 ro 아이콘이 막대 아이콘 줄의 첫 칸(시계 쪽 끝)에 놓이게 한다.
    /// AppKit은 자리를 'NSStatusItem Preferred Position <이름>'(오른쪽 끝에서의 거리)으로 기억하므로,
    /// 아이콘을 보이기 직전마다 가장 작은 값으로 되돌린다.
    private func pinStatusItemFirst() {
        UserDefaults.standard.set(1, forKey: "NSStatusItem Preferred Position \(statusAutosaveName)")
    }

    private func recordsTitle(_ today: Int) -> String {
        roLang == "ko" ? "오늘 \(today)건" : "\(today) records today"
    }

    /// 상태 아이콘은 한 번만 만들고, 메뉴는 언어가 바뀌면 다시 만든다
    private func setupStatusItem() {
        if statusItem == nil {
            pinStatusItemFirst()
            statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
            statusItem.autosaveName = statusAutosaveName
            if let btn = statusItem.button {
                // 메뉴를 직접 띄워야 '끌어 내리기'와 '눌러서 메뉴'를 구분할 수 있다
                btn.target = self
                btn.action = #selector(statusButtonPressed)
                btn.sendAction(on: [.leftMouseDown, .rightMouseDown])
                btn.image = makeIcon(iconPose(nil, gait: .calm))
                btn.toolTip = "ro — three layers, two eyes."
            }
        }
        lookItems = []; sizeItems = []; reactItems = []; matItems = []
        let menu = NSMenu()
        menu.addItem(makeHeaderItem())
        menu.addItem(NSMenuItem.separator())
        talkItem = NSMenuItem(title: L(bubbleOpen ? "Close panel" : "Open panel"), action: #selector(toggleBubble), keyEquivalent: "k")
        talkItem.target = self
        menu.addItem(talkItem)
        if !miniEdition {
            let paletteItem = NSMenuItem(title: L("Command palette (⌥R)"), action: #selector(openPalette), keyEquivalent: "")
            paletteItem.target = self
            menu.addItem(paletteItem)
        }

        // 표정·모션은 설정이 아니라 구경용이라 '미리보기' 하위 메뉴 하나로 묶는다
        let previewMenu = NSMenu()
        let moods: [(String, String)] = [
            ("Idle", "idle"), ("Recording", "recording"), ("Focus", "focus"),
            ("Attention", "anxious"), ("Discovery", "discovery"), ("Resolved", "resolved")
        ]
        previewMenu.addItem(menuSection(L("Expression")))
        for (title, code) in moods {
            let item = NSMenuItem(title: L(title), action: #selector(previewMood(_:)), keyEquivalent: "")
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
        previewMenu.addItem(menuSection(L("Motion")))
        for (title, code) in actions {
            let item = NSMenuItem(title: L(title), action: #selector(triggerActionFromMenu(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = code
            previewMenu.addItem(item)
        }
        // 반응은 실제 앱 없이도 볼 수 있게 한다(쿨다운·설정은 무시, 선점 규칙은 그대로)
        let reactTitles: [(String, ReactKind)] = [("Open", .open), ("Mail", .mail), ("Message", .message)]
        previewMenu.addItem(NSMenuItem.separator())
        previewMenu.addItem(menuSection(L("Reactions")))
        for (title, kind) in reactTitles {
            let item = NSMenuItem(title: L(title), action: #selector(previewReaction(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = kind.rawValue
            previewMenu.addItem(item)
        }
        let previewRoot = NSMenuItem(title: L("Preview expressions & motion"), action: nil, keyEquivalent: "")
        previewRoot.submenu = previewMenu

        let matMenu = NSMenu()
        let materials: [(String, String)] = [
            ("Clay", "clay"), ("Glass", "glass")
        ]
        for (title, code) in materials {
            let item = NSMenuItem(title: L(title), action: #selector(selectMaterial(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = code
            item.state = materialName == code ? .on : .off
            matItems.append(item)
            matMenu.addItem(item)
        }
        let matRoot = NSMenuItem(title: L("Material"), action: nil, keyEquivalent: "")
        matRoot.submenu = matMenu
        menu.addItem(NSMenuItem.separator())
        menu.addItem(matRoot)

        let sizeMenu = NSMenu()
        for (title, code) in [("Small", "small"), ("Medium", "medium"), ("Big", "big")] {
            let item = NSMenuItem(title: L(title), action: #selector(selectSize(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = code
            item.state = sizeName == code ? .on : .off
            sizeItems.append(item)
            sizeMenu.addItem(item)
        }
        let sizeRoot = NSMenuItem(title: L("Size"), action: nil, keyEquivalent: "")
        sizeRoot.submenu = sizeMenu
        menu.addItem(sizeRoot)

        let lookMenu = NSMenu()
        // 상태창 색. ro 색은 상태창 본문에서 고른다
        let looks: [(String, [(String, String)])] = [
            ("panel", [("System", "auto"), ("Light", "light"), ("Dark", "dark")])
        ]
        for (key, choices) in looks {
            for (label, value) in choices {
                let item = NSMenuItem(title: L(label), action: #selector(selectLook(_:)), keyEquivalent: "")
                item.target = self
                item.representedObject = [key, value]
                item.state = lookPrefs[key] == value ? .on : .off
                lookItems.append(item)
                lookMenu.addItem(item)
            }
        }
        let lookRoot = NSMenuItem(title: L("Panel color"), action: nil, keyEquivalent: "")
        lookRoot.submenu = lookMenu
        menu.addItem(lookRoot)

        // 언어: 상태창이 아니라 여기(설정 메뉴)에서 고른다. 이름은 각 언어 그대로 적는다
        let langMenu = NSMenu()
        for (label, value) in [("English", "en"), ("한국어", "ko")] {
            let item = NSMenuItem(title: label, action: #selector(selectLook(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = ["lang", value]
            item.state = lookPrefs["lang"] == value ? .on : .off
            lookItems.append(item)
            langMenu.addItem(item)
        }
        let langRoot = NSMenuItem(title: L("Language"), action: nil, keyEquivalent: "")
        langRoot.submenu = langMenu
        menu.addItem(langRoot)

        wanderItem = NSMenuItem(title: L("Wander"), action: #selector(toggleWander), keyEquivalent: "w")
        wanderItem.target = self
        wanderItem.state = wanderEnabled ? .on : .off
        menu.addItem(wanderItem)
        let reactMenu = NSMenu()
        reactMenu.autoenablesItems = false  // 전체 스위치(상태창의 Reactions)가 꺼져 있으면 종류별 항목을 흐리게 둔다
        for (title, kind) in reactTitles {
            let item = NSMenuItem(title: L(title), action: #selector(toggleReactionKind(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = kind.rawValue
            item.state = reactKinds.contains(kind) ? .on : .off
            item.isEnabled = reactEnabled
            reactItems.append(item)
            reactMenu.addItem(item)
        }
        let reactRoot = NSMenuItem(title: L("Reactions"), action: nil, keyEquivalent: "")
        reactRoot.submenu = reactMenu
        menu.addItem(reactRoot)
        menu.addItem(previewRoot)

        modeItem = NSMenuItem(title: L(mode == .menubar ? "Bring to desktop" : "Send to menu bar"), action: #selector(toggleMode), keyEquivalent: "")
        modeItem.target = self
        menu.addItem(modeItem)

        let resetItem = NSMenuItem(title: L("Call to bottom right"), action: #selector(resetPosition), keyEquivalent: "0")
        resetItem.target = self
        menu.addItem(resetItem)

        // 로그인할 때 열기: 앱 번들(ro.app)로 실행했을 때만. 개발용 단독 실행 파일은 등록할 앱이 없다
        if #available(macOS 13.0, *), Bundle.main.bundleURL.pathExtension == "app" {
            let item = NSMenuItem(title: L("Open at login"), action: #selector(toggleLoginItem), keyEquivalent: "")
            item.target = self
            item.state = SMAppService.mainApp.status == .enabled ? .on : .off
            loginItem = item
            menu.addItem(item)
        }

        if miniEdition {   // 자동 활성화: 결제가 끝나면 ro가 스스로 키를 받아 pro로 다시 연다(ro/licensenet.py)
            let proItem = NSMenuItem(title: L("Get pro…"), action: #selector(openGetPro), keyEquivalent: "")
            proItem.target = self
            menu.addItem(proItem)
        }
        let licenseItem = NSMenuItem(title: L("License…"), action: #selector(openLicense), keyEquivalent: "")
        licenseItem.target = self
        menu.addItem(licenseItem)

#if canImport(Sparkle)
        if let updaterController = updaterController {
            let updateItem = NSMenuItem(title: L("Check for updates…"), action: #selector(SPUStandardUpdaterController.checkForUpdates(_:)), keyEquivalent: "")
            updateItem.target = updaterController
            menu.addItem(updateItem)
        }
#endif
        menu.addItem(NSMenuItem.separator())
        let quitItem = NSMenuItem(title: L("Quit ro pet"), action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        mainMenu = menu
    }

    // 메뉴 첫 줄: 오늘 기록 수와 지금 표정. 숫자는 웹이 폴링할 때 넘겨준다
    private func makeHeaderItem() -> NSMenuItem {
        headerTitle = NSTextField(labelWithString: miniEdition ? "ro.bot" : (lastToday.map { self.recordsTitle($0) } ?? L("Loading today's records")))
        headerTitle.font = NSFont.boldSystemFont(ofSize: 13)
        headerDetail = NSTextField(labelWithString: L("Measuring CPU"))
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
            showToast(L("Could not change the login setting"), L("Check System Settings › General › Login Items"))
        }
        loginItem?.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }

    // ---- pro 라이선스: 키는 웹 화면을 거쳐 로컬 서버(/api/license)로만 간다. 화면·로그에 키를 남기지 않는다 ----
    @objc private func openGetPro() {
        let alert = NSAlert()
        alert.messageText = L("Get ro pro")
        alert.informativeText = L("Pay in your browser. When the payment goes through, ro turns pro on by itself — no key to paste.")
        alert.addButton(withTitle: L("Yearly · $24"))
        alert.addButton(withTitle: L("Monthly · $3"))
        alert.addButton(withTitle: L("Cancel"))
        NSApp.activate(ignoringOtherApps: true)
        let choice = alert.runModal()
        let plan = choice == .alertFirstButtonReturn ? "yearly" : choice == .alertSecondButtonReturn ? "monthly" : ""
        guard !plan.isEmpty else { return }
        licenseCall(["action": "buy", "plan": plan]) { res in
            if (res["ok"] as? Bool) == true, let s = res["url"] as? String, let url = URL(string: s), url.scheme == "https" {
                NSWorkspace.shared.open(url)   // 결제는 브라우저에서. 호스트는 연락하지 않는다
                return
            }
            let fail = NSAlert()
            fail.alertStyle = .warning
            fail.messageText = L("Could not start the purchase")
            fail.informativeText = (res["error"] as? String) ?? ""
            NSApp.activate(ignoringOtherApps: true)
            fail.runModal()
        }
    }

    @objc private func openLicense() {
        licenseCall(["action": "status"]) { [weak self] st in self?.showLicenseDialog(st) }
    }

    private func licenseCall(_ body: [String: Any], done: @escaping ([String: Any]) -> Void) {
        webView.callAsyncJavaScript("return await window.licenseFromHost(body);", arguments: ["body": body],
                                    in: nil, in: .page) { result in
            var res: [String: Any] = ["ok": false, "error": "auth"]
            if case .success(let value) = result, let dict = value as? [String: Any] { res = dict }
            if (res["error"] as? String) == "auth" {
                res["error"] = L("Could not reach ro. Quit and reopen the pet, then try again.")
            }
            done(res)
        }
    }

    private func showLicenseDialog(_ st: [String: Any]) {
        let alert = NSAlert()
        alert.messageText = L("ro pro license")
        let current = (st["message"] as? String) ?? (st["error"] as? String) ?? ""
        alert.informativeText = current + "\n\n" + L("Paste the key from your purchase email. It is checked on this Mac only, without the internet.")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 340, height: 24))
        field.placeholderString = "RO1.…"
        field.usesSingleLineMode = true
        field.cell?.isScrollable = true
        // 자동 받기(ro/licensenet.py): 발급기 주소가 있을 때만 보인다. 끄면 ro는 키를 받으러 연락하지 않는다
        var autoBox: NSButton? = nil
        if (st["autoReady"] as? Bool) == true {
            let box = NSButton(checkboxWithTitle: L("Get my key automatically"), target: nil, action: nil)
            box.state = ((st["auto"] as? Bool) ?? true) ? .on : .off
            autoBox = box
            let stack = NSStackView(views: [field, box])
            stack.orientation = .vertical
            stack.alignment = .leading
            stack.spacing = 10
            stack.frame = NSRect(x: 0, y: 0, width: 340, height: 56)
            alert.accessoryView = stack
        } else {
            alert.accessoryView = field
        }
        alert.addButton(withTitle: L("Save key"))
        alert.addButton(withTitle: L("Cancel"))
        let hasKey = (st["state"] as? String).map { $0 != "none" } ?? false
        if hasKey { alert.addButton(withTitle: L("Remove key")) }
        NSApp.activate(ignoringOtherApps: true)
        alert.window.initialFirstResponder = field
        let choice = alert.runModal()
        if let box = autoBox {
            let on = box.state == .on
            if on != ((st["auto"] as? Bool) ?? true) { licenseCall(["action": "auto", "on": on]) { _ in } }
        }
        if choice == .alertFirstButtonReturn {
            let key = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty else { return }
            licenseCall(["action": "set", "key": key]) { [weak self] res in self?.finishLicense(res, saved: true) }
        } else if hasKey && choice == .alertThirdButtonReturn {
            let confirm = NSAlert()
            confirm.messageText = L("Remove the license key from this Mac? ro goes back to mini. Your files and records stay as they are.")
            confirm.addButton(withTitle: L("Remove key"))
            confirm.addButton(withTitle: L("Cancel"))
            guard confirm.runModal() == .alertFirstButtonReturn else { return }
            licenseCall(["action": "remove"]) { [weak self] res in self?.finishLicense(res, saved: false) }
        }
    }

    private func finishLicense(_ res: [String: Any], saved: Bool) {
        let ok = (res["ok"] as? Bool) ?? false
        let restart = (res["restart"] as? Bool) ?? false
        let alert = NSAlert()
        alert.alertStyle = ok ? .informational : .warning
        alert.messageText = ok ? L(saved ? "License saved" : "Key removed") : L("Could not save the key")
        var info = (ok ? res["message"] : res["error"]) as? String ?? ""
        if restart { info += "\n\n" + L("ro restarts to apply it. Your files and records stay as they are.") }
        alert.informativeText = info
        alert.addButton(withTitle: restart ? L("Restart ro now") : "OK")
        if restart { alert.addButton(withTitle: L("Later")) }
        NSApp.activate(ignoringOtherApps: true)
        // 다시 시작: 이 종료 코드로 끝날 때만 ro(Python)가 같은 실행기 환경으로 자신을 다시 연다(ro/pet.py RESTART_EXIT)
        if alert.runModal() == .alertFirstButtonReturn && restart { exit(75) }
    }

    @objc private func statusButtonPressed() {
        guard let event = NSApp.currentEvent, let btn = statusItem.button else { return }
        if event.type == .rightMouseDown {
            showStatusMenu()
            return
        }
        // 누른 채 아래로 끌면 펫으로 꺼내고, 그대로 떼면 메뉴를 연다
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

    // 끌어 내린 커서 아래에 펫을 띄우고 그대로 드래그를 이어 받는다
    /// 펫 우클릭은 화면 아래쪽에서 일어난다. 아래로 다 안 들어가면 위로 열어 종료·업데이트 항목이 스크롤 없이 보이게 한다
    private func popUpMainMenu(at p: NSPoint) {
        let h = mainMenu.size.height
        let floor = (NSScreen.screens.first { $0.frame.contains(p) } ?? NSScreen.main)?.visibleFrame.minY ?? 0
        let y = (p.y - h < floor) ? p.y + h : p.y
        mainMenu.popUp(positioning: nil, at: NSPoint(x: p.x, y: y), in: nil)
    }
    private func popOut(at mouse: NSPoint) {
        savedDesktopOrigin = nil
        panel.setFrameOrigin(NSPoint(x: mouse.x - compactSize.width / 2, y: mouse.y - compactSize.height + 40))
        setMode(.desktop)
        startNativeDrag(fromPet: true)
    }

    // 메뉴 막대 모드에서 펫(과 패널)이 내려올 자리: 아이콘 바로 아래
    private func menubarAnchorOrigin() -> NSPoint {
        let vf = currentVisibleFrame()
        let midX = statusItem.button?.window?.frame.midX ?? (vf.maxX - compactSize.width / 2)
        return NSPoint(x: midX - compactSize.width / 2, y: vf.maxY - compactSize.height)
    }

    // 모드 전환은 여기 한 곳에서만 한다: 펫 창, 상태 아이콘, 저장
    private func setMode(_ next: PetMode) {
        if next != mode && bubbleOpen {
            webView.evaluateJavaScript("window.toggleBubbleFromHost && window.toggleBubbleFromHost(false);", completionHandler: nil)
            setBubbleState(false)
        }
        if next == .desktop, let origin = savedDesktopOrigin {
            panel.setFrameOrigin(origin)
            savedDesktopOrigin = nil
        }
        if next == .desktop { fitPanelToCompactSize() }  // 메뉴 막대에 있는 동안 크기를 바꿨을 수 있다
        mode = next
        defaults.set(next.rawValue, forKey: "ro.mode")
        if next == .menubar { pinStatusItemFirst() }
        statusItem.isVisible = (next == .menubar)
        DispatchQueue.main.async { [weak self] in self?.updateIconAnimation() }  // 아이콘 창 배치 뒤에
        modeItem.title = L(next == .menubar ? "Bring to desktop" : "Send to menu bar")
        if next == .menubar {
            panel.orderOut(nil)
        } else {
            panel.orderFrontRegardless()
        }
    }

    // 메뉴 막대 모드에서는 말풍선이 열려 있을 때만 창을 보인다
    private func revealPet() {
        if mode == .desktop || bubbleOpen {
            panel.orderFrontRegardless()
        } else {
            panel.orderOut(nil)
        }
    }

    /// 미리보기(표정·모션·반응)를 볼 수 있게 펫을 보인다. 메뉴 막대 모드면 아이콘 아래에 seconds 동안만 꺼냈다가 다시 넣는다
    private func revealPetForPreview(seconds: TimeInterval) {
        previewHide?.cancel()
        previewHide = nil
        guard mode == .menubar, !bubbleOpen else { revealPet(); return }
        savedDesktopOrigin = savedDesktopOrigin ?? panel.frame.origin
        fitPanelToCompactSize()  // 숨어 있는 동안 크기를 바꿨을 수 있다
        panel.setFrameOrigin(menubarAnchorOrigin())
        panel.orderFrontRegardless()
        let work = DispatchWorkItem { [weak self] in
            guard let self = self else { return }
            self.previewHide = nil
            self.revealPet()  // 그 사이 패널을 열었거나 데스크톱으로 꺼냈으면 그대로 둔다
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
        // 지난번에 놓아 둔 자리(그 화면이 아직 있을 때만)
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
        // 전체 화면 앱 위에는 띄우지 않는다. .stationary: 데스크톱 보기·Exposé가 앱 창과 함께 펫을 치우지 않게 한다
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        panel.isMovableByWindowBackground = false

        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "roHost")
        webView = PetWebView(frame: NSRect(origin: .zero, size: compactSize), configuration: config)
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        webView.autoresizingMask = [.width, .height]

        // 시스템 유리는 웹 화면 아래에 깔리고, 마우스는 위의 웹 화면이 받는다
        NativeGlass.forceBlur = defaults.string(forKey: "ro.glass") == "blur"
        if !NativeGlass.forceBlur { NativeGlass.forceActiveAppearance(panel) }
        let container = FlippedView(frame: NSRect(origin: .zero, size: compactSize))
        glassLayer = FlippedView(frame: container.bounds)
        glassLayer.autoresizingMask = [.width, .height]
        glassLayer.isHidden = true
        container.addSubview(glassLayer)
        container.addSubview(webView)
        panel.contentView = container
        // 펫 창이 활성/비활성으로 바뀌면 굴절 유리 ↔ 흐림 유리를 바꾼다
        for name in [NSWindow.didBecomeKeyNotification, NSWindow.didResignKeyNotification] {
            NotificationCenter.default.addObserver(forName: name, object: panel, queue: .main) { [weak self] _ in
                self?.refreshGlass()
            }
        }
        if let url = URL(string: urlString) {
            webView.load(URLRequest(url: url))
        }
    }

    /// 펫 화면은 ro 로컬 서버 한 곳만 띄운다. 다른 주소로의 이동(링크·리디렉션)은 막는다
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let home = URL(string: urlString)
        let target = navigationAction.request.url
        let sameOrigin = target?.scheme == home?.scheme && target?.host == home?.host && target?.port == home?.port
        decisionHandler(sameOrigin || target?.absoluteString == "about:blank" ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.evaluateJavaScript("window.setWanderState && window.setWanderState(\(wanderEnabled));", completionHandler: nil)
        webView.evaluateJavaScript("window.setPetSize && window.setPetSize('\(sizeName)');", completionHandler: nil)  // 다시 불러도 크기 유지
        webView.evaluateJavaScript("window.setReactState && window.setReactState(\(reactEnabled));", completionHandler: nil)
        webView.evaluateJavaScript("window.setNativeGlass && window.setNativeGlass('\(glassKind)');", completionHandler: nil)
    }

    /// 창 크기나 활성 상태가 바뀌면, 예전 유리를 걷고 웹 화면에 유리 종류를 다시 알려 자리를 다시 받는다
    private func refreshGlass() {
        glassLayer.isHidden = true
        webView.evaluateJavaScript("window.setNativeGlass && window.setNativeGlass('\(glassKind)');", completionHandler: nil)
    }

    /// 웹 화면이 알려 준 몸통 세 층의 자리·기울기·불투명도에 유리를 맞춘다. on=false(재질이 다르거나 펫이 숨음)면 걷는다
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
        CATransaction.setDisableActions(true)  // 숨쉬기·흔들기를 따라갈 때 미끄러지는 애니메이션 없이 바로 옮긴다
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

    // 1초마다 전체 CPU 사용률을 읽어 걸음 단계를 정한다. 화면이 꺼지거나 잠기면 쉬고, 돌아오면 처음부터
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
        timer.tolerance = 0.3  // 다른 타이머와 묶여 깨어나는 횟수를 줄인다
        RunLoop.main.add(timer, forMode: .common)
        cpuTimer = timer
    }

    private func stopCPUSampler() {
        cpuTimer?.invalidate()
        cpuTimer = nil
        lastTicks = nil
        smoother.reset()
        overheatGate.reset()
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
        headerDetail.stringValue = "CPU \(shown)% · \(L(gait.label))"
        if overheatGate.push(pct) {
            startOverheatScan(busy: overheatGate.window.mean)
        }
    }

    // MARK: 과열 알림. 앱별 사용량은 그때만 2초 재고, 이름은 이 Mac 밖으로도 로그로도 나가지 않는다

    private func todayString() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }

    private func startOverheatScan(busy: Double) {
        let today = todayString()
        let memoDay = defaults.string(forKey: "ro.overheat.day")
        if memoDay == today && defaults.bool(forKey: "ro.overheat.muted") { return }  // 오늘은 그만
        guard !overheatScanning else { return }
        overheatScanning = true
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let culprit = Self.scanTopApp()
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.overheatScanning = false
                self.presentOverheat(culprit: culprit, busy: busy)
            }
        }
    }

    // 프로세스별 CPU 시간(초)과 앱 이름. rusage를 못 읽는 프로세스(시스템·root)는 빠진다
    private static func processCPU() -> [pid_t: (app: String, seconds: Double)] {
        var tb = mach_timebase_info()
        mach_timebase_info(&tb)
        let n = proc_listallpids(nil, 0)
        guard n > 0 else { return [:] }
        var pids = [pid_t](repeating: 0, count: Int(n) * 2)
        let got = proc_listallpids(&pids, Int32(pids.count * MemoryLayout<pid_t>.size))
        var out: [pid_t: (String, Double)] = [:]
        var pathBuf = [CChar](repeating: 0, count: 4096)
        for pid in pids.prefix(Int(max(0, got))) where pid > 0 {
            var info = rusage_info_v4()
            let rc = withUnsafeMutablePointer(to: &info) {
                $0.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) { proc_pid_rusage(pid, RUSAGE_INFO_V4, $0) }
            }
            guard rc == 0 else { continue }
            let len = proc_pidpath(pid, &pathBuf, UInt32(pathBuf.count))
            let path = len > 0 ? String(cString: pathBuf) : ""
            let secs = machToSeconds(info.ri_user_time + info.ri_system_time, numer: tb.numer, denom: tb.denom)
            out[pid] = (appName(forExecutablePath: path), secs)
        }
        return out
    }

    // 2초 동안 앱별로 CPU의 몇 %를 썼는지 재고, 읽지 못한 몫과 비교해 이름을 댈지 정한다
    private static func scanTopApp() -> (name: String, share: Double)? {
        guard let t0 = CPUTicks.read() else { return nil }
        let a = processCPU()
        Thread.sleep(forTimeInterval: 2.0)
        guard let t1 = CPUTicks.read(), let busy = cpuPercent(from: t0, to: t1) else { return nil }
        let b = processCPU()
        let capacity = Double(t1.total &- t0.total) / Double(sysconf(Int32(_SC_CLK_TCK)))  // 코어 수 × 경과 초
        guard capacity > 0 else { return nil }
        var usage: [String: Double] = [:]
        for (pid, now) in b {
            guard let before = a[pid], now.seconds >= before.seconds else { continue }
            usage[now.app, default: 0] += (now.seconds - before.seconds) / capacity * 100
        }
        let readable = usage.values.reduce(0, +)
        return overheatCulprit(usage, unreadable: max(0, busy - readable))
    }

    private func presentOverheat(culprit: (name: String, share: Double)?, busy: Double) {
        let today = todayString()
        let memoDay = defaults.string(forKey: "ro.overheat.day")
        var alerted = (memoDay == today) ? (defaults.stringArray(forKey: "ro.overheat.apps") ?? []) : []
        guard shouldAlertOverheat(app: culprit?.name, today: today, memoDay: memoDay,
                                  muted: defaults.bool(forKey: "ro.overheat.muted"), alerted: alerted) else { return }
        if memoDay != today { defaults.set(false, forKey: "ro.overheat.muted") }
        alerted.append(culprit?.name ?? "")
        defaults.set(today, forKey: "ro.overheat.day")
        defaults.set(alerted, forKey: "ro.overheat.apps")

        // CPU %는 메뉴의 숫자와 같은 'Mac 전체 대비'다 (활동 모니터의 코어당 %와 다르다)
        let detail = culprit.map { "Busiest app: \($0.name) (CPU \(Int($0.share.rounded()))%) · busy for a minute" }
            ?? "CPU at \(Int(busy.rounded()))% for a minute · the app could not be identified"
        showOverheatCard(detail: detail)
    }

    private func showOverheatCard(detail: String) {
        alertPanel?.orderOut(nil)
        let title = NSTextField(labelWithString: L("Your Mac is struggling"))
        title.font = NSFont.boldSystemFont(ofSize: 13)
        let body = NSTextField(wrappingLabelWithString: detail)
        body.font = NSFont.systemFont(ofSize: 12)
        body.textColor = .secondaryLabelColor
        body.preferredMaxLayoutWidth = 260
        let open = NSButton(title: L("Open Activity Monitor"), target: self, action: #selector(openActivityMonitor))
        open.bezelStyle = .rounded
        open.keyEquivalent = "\r"
        let mute = NSButton(title: L("Not today"), target: self, action: #selector(muteOverheatToday))
        mute.bezelStyle = .inline
        let buttons = NSStackView(views: [open, mute])
        buttons.spacing = 10
        let stack = NSStackView(views: [title, body, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8
        stack.edgeInsets = NSEdgeInsets(top: 14, left: 16, bottom: 14, right: 16)
        let size = stack.fittingSize

        let box = NSVisualEffectView(frame: NSRect(origin: .zero, size: size))
        box.material = .popover
        box.state = .active
        box.wantsLayer = true
        box.layer?.cornerRadius = 12
        stack.frame = box.bounds
        box.addSubview(stack)

        // 메뉴 막대 모드는 아이콘 아래, 데스크톱 모드는 펫 옆
        let vf = currentVisibleFrame()
        var origin: NSPoint
        if mode == .menubar, let icon = statusItem.button?.window?.frame {
            origin = NSPoint(x: icon.midX - size.width / 2, y: vf.maxY - size.height - 8)
        } else {
            let pet = panel.frame
            origin = NSPoint(x: pet.minX - size.width - 8, y: pet.maxY - size.height)
            if origin.x < vf.minX + 8 { origin.x = pet.maxX + 8 }
        }
        origin.x = min(max(origin.x, vf.minX + 8), vf.maxX - size.width - 8)
        origin.y = min(max(origin.y, vf.minY + 8), vf.maxY - size.height - 8)
        let card = NSPanel(contentRect: NSRect(origin: origin, size: size),
                           styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        card.isOpaque = false
        card.backgroundColor = .clear
        card.hasShadow = true
        card.level = .statusBar
        card.becomesKeyOnlyIfNeeded = true
        card.collectionBehavior = [.canJoinAllSpaces, .stationary, .transient]
        card.contentView = box
        card.orderFrontRegardless()
        alertPanel = card
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self, weak card] in
            card?.orderOut(nil)
            if self?.alertPanel === card { self?.alertPanel = nil }
        }
    }

    @objc private func openActivityMonitor() {
        alertPanel?.orderOut(nil)
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.ActivityMonitor") {
            NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
        }
    }

    @objc private func muteOverheatToday() {
        alertPanel?.orderOut(nil)
        defaults.set(todayString(), forKey: "ro.overheat.day")
        defaults.set(true, forKey: "ro.overheat.muted")
    }

    // MARK: 메뉴 막대 아이콘 걸음 (07). 데스크톱 펫은 CPU에 맞춰 걷지 않는다

    // 아이콘이 보이고(메뉴 막대 모드, 노치에 안 가림) '동작 줄이기'가 꺼져 있을 때만 뛴다
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

    // 지금 단계의 프레임을 보여 주고 다음 시점까지 기다린다. 사이클 길이는 0.8초 상한(menubarPeriod)
    private func showJumpStep() {
        let step = jumpSchedule[jumpStep]
        statusItem.button?.image = jumpImage(step.frame, gait: iconGait)
        let nextAt = jumpStep + 1 < jumpSchedule.count ? jumpSchedule[jumpStep + 1].at : 1.0
        let delay = (nextAt - step.at) * iconGait.menubarPeriod
        let timer = Timer(timeInterval: delay, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            self.jumpStep = (self.jumpStep + 1) % jumpSchedule.count
            // 착지해 다시 웅크릴 때만 빠르기를 바꾼다 (공중에서 끊기지 않게)
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
        // 노치 뒤로 밀리거나 전체 화면으로 메뉴 막대가 숨으면 그리기를 멈춘다
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

    // MARK: 앱 반응
    private func observeAppReactions() {
        let nc = NSWorkspace.shared.notificationCenter
        let me = ProcessInfo.processInfo.processIdentifier
        nc.addObserver(forName: NSWorkspace.didLaunchApplicationNotification, object: nil, queue: .main) { [weak self] note in
            guard let self = self, self.reactEnabled,
                  let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
                  app.activationPolicy == .regular, app.processIdentifier != me else { return }
            let pid = app.processIdentifier
            let verdict = ReactGate.onLaunch(kind: reactKind(forBundleID: app.bundleIdentifier), alreadyActive: app.isActive)
            if let kind = verdict.emit { self.requestReaction(kind) }
            guard verdict.waitsForActivation else { return }
            self.recentLaunches[pid] = ProcessInfo.processInfo.systemUptime
            // 곧바로 앞에 오면 그 활성화와 합친다. 안 오면 그때 open을 낸다
            let work = DispatchWorkItem { [weak self] in
                self?.pendingOpens[pid] = nil
                self?.recentLaunches[pid] = nil
                self?.requestReaction(.open)
            }
            self.pendingOpens[pid]?.cancel()
            self.pendingOpens[pid] = work
            DispatchQueue.main.asyncAfter(deadline: .now() + ReactGate.mergeWindow, execute: work)
        }
        nc.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] note in
            guard let self = self, self.reactEnabled,
                  let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
                  app.processIdentifier != me else { return }  // 펫 자신이 앞에 오는 것은 무시한다
            let pid = app.processIdentifier
            let since = self.recentLaunches[pid].map { ProcessInfo.processInfo.systemUptime - $0 }
            let verdict = ReactGate.onActivate(kind: reactKind(forBundleID: app.bundleIdentifier), sinceLaunch: since)
            if verdict.cancelsPendingOpen {
                self.pendingOpens[pid]?.cancel()
                self.pendingOpens[pid] = nil
                self.recentLaunches[pid] = nil
            }
            if let kind = verdict.emit { self.requestReaction(kind) }
        }
        for name in [NSWorkspace.screensDidWakeNotification, NSWorkspace.sessionDidBecomeActiveNotification] {
            nc.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                self?.reactGate.woke(at: ProcessInfo.processInfo.systemUptime)
            }
        }
    }

    /// 조건을 거른 뒤 웹 화면에 반응을 청한다. 웹이 실제로 띄웠을 때(true)만 쿨다운을 쓴다.
    /// preview(우클릭 Preview ▸ Reactions)는 설정·쿨다운을 건너뛰지만 웹의 선점 규칙은 그대로 받는다
    private func requestReaction(_ kind: ReactKind, preview: Bool = false) {
        guard preview || mode == .desktop, panel?.isVisible == true, !bubbleOpen, !isDragging else { return }
        if !preview {
            guard reactEnabled, reactKinds.contains(kind),
                  reactGate.allows(kind, at: ProcessInfo.processInfo.systemUptime) else { return }
        }
        webView.evaluateJavaScript("window.petReact ? window.petReact('\(kind.rawValue)') : false") { [weak self] result, _ in
            guard !preview, (result as? Bool) == true else { return }
            self?.reactGate.succeeded(kind, at: ProcessInfo.processInfo.systemUptime)
        }
    }

    @objc private func previewReaction(_ sender: NSMenuItem) {
        guard let raw = sender.representedObject as? String, let kind = ReactKind(rawValue: raw) else { return }
        revealPetForPreview(seconds: 5)
        requestReaction(kind, preview: true)
    }

    @objc private func toggleReactionKind(_ sender: NSMenuItem) {
        guard let raw = sender.representedObject as? String, let kind = ReactKind(rawValue: raw) else { return }
        let on = !reactKinds.contains(kind)
        if on { reactKinds.insert(kind) } else { reactKinds.remove(kind) }
        defaults.set(on, forKey: "ro.react.\(kind.rawValue)")
        sender.state = on ? .on : .off
    }

    private func setReactEnabled(_ enabled: Bool) {
        reactEnabled = enabled
        defaults.set(enabled, forKey: "ro.react.enabled")
        for item in reactItems { item.isEnabled = enabled }
        if !enabled {  // 끄면 기다리던 open도 버린다
            pendingOpens.values.forEach { $0.cancel() }
            pendingOpens.removeAll()
            recentLaunches.removeAll()
        }
        webView?.evaluateJavaScript("window.setReactState && window.setReactState(\(enabled));", completionHandler: nil)
    }

    @objc private func selectSize(_ sender: NSMenuItem) {
        guard let code = sender.representedObject as? String else { return }
        applySize(code)
    }

    /// 크기를 바꾼다(우클릭 메뉴와 설정 칩이 모두 여기로 온다). 값 검증 → 저장 → 웹 화면 → 창 순서다
    private func applySize(_ code: String) {
        guard petSizeScales[code] != nil else { return }
        sizeName = code
        defaults.set(code, forKey: "ro.size")
        for item in sizeItems { item.state = (item.representedObject as? String) == code ? .on : .off }
        webView?.evaluateJavaScript("window.setPetSize && window.setPetSize('\(code)');", completionHandler: nil)
        guard panel != nil else { return }
        if bubbleOpen {
            // 창은 닫을 때 새 크기로 돌아온다. 열 때 적어 둔 자리는 예전 크기 기준이라 버린다
            originBeforeOpen = nil
            return
        }
        guard mode == .desktop else { return }  // 메뉴 막대 모드는 창이 숨어 있다. 꺼낼 때 맞춘다
        fitPanelToCompactSize()
        savePosition(delay: 0.2)  // 저장 자리는 창 왼쪽 아래 기준이라 크기와 함께 갱신한다
    }

    /// 접힌 창을 지금 크기에 맞춘다. 펫이 앉은 아래·오른쪽 모서리를 고정하고, 웹 쪽 전환이 있으므로 창은 한 번에 바꾼다
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

    /// 데스크톱 펫 자리(말풍선을 접은 기준)를 저장해 다음 실행 때 같은 곳에 띄운다.
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
            // 데스크톱 모드에선 상태 아이콘이 숨으므로 펫 우클릭이 같은 메뉴로 가는 길이다
            popUpMainMenu(at: NSEvent.mouseLocation)
        } else if type == "status" {
            let today = (dict["today"] as? NSNumber)?.intValue ?? 0
            lastToday = today
            headerTitle.stringValue = miniEdition ? "ro.bot" : recordsTitle(today)
        } else if type == "bubble" {
            let open = (dict["open"] as? Bool) ?? false
            setBubbleState(open)
        } else if type == "openCheckout" {
            if let s = dict["url"] as? String, let url = URL(string: s), url.scheme == "https" {
                NSWorkspace.shared.open(url)
            }
        } else if type == "restartLicense" {
            exit(75)
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
            if let lang = dict["lang"] as? String, lang == "en" || lang == "ko" {
                lookPrefs["lang"] = lang
                for item in lookItems {
                    guard let choice = item.representedObject as? [String], choice.count == 2, choice[0] == "lang" else { continue }
                    item.state = choice[1] == lang ? .on : .off
                }
                if lang != roLang {
                    roLang = lang
                    setupStatusItem()  // 메뉴 문구를 새 언어로 다시 만든다
                }
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
        } else if type == "react" {
            if let enabled = dict["enabled"] as? Bool { setReactEnabled(enabled) }
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
    // 메뉴 막대 앱은 거의 종료하지 않아서 "종료할 때 설치"로 두면 업데이트가 영영 안 된다.
    // 꾸미기(mini) 에디션은 하던 일이 없으니 받자마자 설치하고 다시 연다. 기능(pro)은 파일을 옮기는 중일 수 있어 종료 때까지 미룬다.
    func updater(_ updater: SPUUpdater, willInstallUpdateOnQuit item: SUAppcastItem, immediateInstallationBlock immediateInstallHandler: @escaping () -> Void) -> Bool {
        guard miniEdition else { return false }
        immediateInstallHandler()
        return true
    }
}
#endif

// MARK: ro pro 센서 — 표준출력 JSON-Lines. mini에서는 만들지도 않는다. 네트워크 API를 쓰지 않는다(ro eval no_network).
// 보내는 것: 앞 앱 이름·실행 직후 여부·전체 화면, HID 유휴 초, 카메라·마이크 사용 여부, (손쉬운 사용 권한이 있을 때)
// 창 전환 3종과 앞 문서 경로. 창 제목·키 입력·화면 내용은 보내지 않는다.

enum IdleBucket: String { case typing, active, away }

/// 유휴 시간을 5초마다 읽는다. 구간이 바뀌거나, 입력 중이거나(파이썬이 외삽하지 않게), heartbeat가 지났을 때만 보낸다
struct IdleTracker {
    static let typingBelow = 2.5, awayAfter = 300.0, heartbeat = 15.0, every = 5.0
    var last: IdleBucket? = nil
    var lastSent: TimeInterval = -1e9
    static func bucket(_ s: Double) -> IdleBucket { s < typingBelow ? .typing : (s < awayAfter ? .active : .away) }
    mutating func shouldSend(seconds: Double, now: TimeInterval) -> Bool {
        let b = IdleTracker.bucket(seconds)
        if b != last || b == .typing || now - lastSent >= IdleTracker.heartbeat { last = b; lastSent = now; return true }
        return false
    }
}

func hidIdleSeconds() -> Double? {
    let service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("IOHIDSystem"))
    guard service != 0 else { return nil }
    defer { IOObjectRelease(service) }
    guard let prop = IORegistryEntryCreateCFProperty(service, "HIDIdleTime" as CFString, kCFAllocatorDefault, 0)?
            .takeRetainedValue() as? NSNumber else { return nil }
    return prop.doubleValue / 1e9
}

/// 창 위치만 본다(제목은 화면 기록 권한이 필요하고, 보내지도 않는다)
func isFullScreen(pid: pid_t) -> Bool {
    guard let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            as? [[String: Any]] else { return false }
    let screens = NSScreen.screens.map { $0.frame.size }
    for w in info where (w[kCGWindowOwnerPID as String] as? pid_t) == pid && (w[kCGWindowLayer as String] as? Int) == 0 {
        guard let b = w[kCGWindowBounds as String] as? [String: CGFloat],
              let wd = b["Width"], let ht = b["Height"] else { continue }
        if screens.contains(where: { abs($0.width - wd) < 1 && abs($0.height - ht) < 1 }) { return true }
    }
    return false
}

/// 카메라·마이크 사용 여부. 폴링하지 않고 OS 알림(KVO·CoreAudio 리스너)으로 바뀔 때만 다시 센다
final class CaptureWatch {
    private var cameras: [AVCaptureDevice] = []
    private var kvo: [NSKeyValueObservation] = []
    private var micDevice = AudioObjectID(0)
    private var micListener: AudioObjectPropertyListenerBlock?
    private var defaultListener: AudioObjectPropertyListenerBlock?
    private var last: Bool? = nil
    var changed: ((Bool) -> Void)?

    func start() {
        reloadCameras()
        for name in [AVCaptureDevice.wasConnectedNotification, AVCaptureDevice.wasDisconnectedNotification] {
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                self?.reloadCameras()
            }
        }
        var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultInputDevice,
                                              mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        let onDefault: AudioObjectPropertyListenerBlock = { [weak self] _, _ in self?.followMic() }
        defaultListener = onDefault
        AudioObjectAddPropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject), &addr, .main, onDefault)
        followMic()
    }

    private func reloadCameras() {
        var types: [AVCaptureDevice.DeviceType] = [.builtInWideAngleCamera]
        if #available(macOS 14.0, *) { types.append(.external) }
        cameras = AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .video, position: .unspecified).devices
        kvo = cameras.map { $0.observe(\.isInUseByAnotherApplication, options: []) { [weak self] _, _ in
            DispatchQueue.main.async { self?.report() }
        } }
        report()
    }

    private func followMic() {
        var addr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyDeviceIsRunningSomewhere,
                                              mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        if micDevice != 0, let l = micListener {
            AudioObjectRemovePropertyListenerBlock(micDevice, &addr, .main, l)
        }
        var dev = AudioObjectID(0)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        var defAddr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultInputDevice,
                                                 mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &defAddr, 0, nil, &size, &dev)
        micDevice = dev
        if dev != 0 {
            let l: AudioObjectPropertyListenerBlock = { [weak self] _, _ in self?.report() }
            micListener = l
            AudioObjectAddPropertyListenerBlock(dev, &addr, .main, l)
        }
        report()
    }

    private func micRunning() -> Bool {
        guard micDevice != 0 else { return false }
        var running: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        var addr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyDeviceIsRunningSomewhere,
                                              mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        guard AudioObjectGetPropertyData(micDevice, &addr, 0, nil, &size, &running) == noErr else { return false }
        return running != 0
    }

    private func report() {
        let now = micRunning() || cameras.contains { $0.isInUseByAnotherApplication }
        if now != last { last = now; changed?(now) }
    }
}

final class ProSensor {
    static let shared = ProSensor()
    private let out = DispatchQueue(label: "ro.pro.out")
    private let axQueue = DispatchQueue(label: "ro.pro.ax", qos: .utility)   // Finder·문서 조회는 여기서만(직렬)
    private var idle = IdleTracker()
    private let capture = CaptureWatch()
    private var launched: [pid_t: TimeInterval] = [:]
    private var timer: Timer?
    private var axObserver: AXObserver?
    private var axPid: pid_t = 0
    private var axWork: DispatchWorkItem?
    private var axTrusted = false
    private var lastAxDoc: String? = nil
    private var frontPid: pid_t = 0
    private var frontFull = false
    static let axDelay = 0.25
    private let axNames = [kAXFocusedWindowChangedNotification, kAXMainWindowChangedNotification,
                           kAXWindowCreatedNotification, kAXTitleChangedNotification]   // Finder 단일 창 이동 감지 포함(AXUIElementDestroyed는 초당 14회 소음이라 제외)
    var onCommand: (([String: Any]) -> Void)?

    func emit(_ d: [String: Any]) {
        var d = d
        d["t"] = Date().timeIntervalSince1970
        out.async {
            guard let data = try? JSONSerialization.data(withJSONObject: d) else { return }
            var line = data
            line.append(0x0A)
            line.withUnsafeBytes { raw in _ = Darwin.write(1, raw.baseAddress, raw.count) }  // 파이프가 끊겨도 죽지 않는다(SIGPIPE 무시)
        }
    }

    func start() {
        signal(SIGPIPE, SIG_IGN)
        axTrusted = AXIsProcessTrusted()   // 묻지 않는다. 없으면 NSWorkspace+HIDIdleTime만 쓰고 poll()에서 다시 확인한다
        emit(["type": "ready", "ax": axTrusted])
        let nc = NSWorkspace.shared.notificationCenter
        let me = ProcessInfo.processInfo.processIdentifier
        nc.addObserver(forName: NSWorkspace.didLaunchApplicationNotification, object: nil, queue: .main) { [weak self] note in
            guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
            self?.launched[app.processIdentifier] = ProcessInfo.processInfo.systemUptime
        }
        nc.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] note in
            guard let self = self, let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
                  app.processIdentifier != me else { return }
            self.front(app)
        }
        // 전체 화면에 들어가고 나올 때는 Space가 바뀐다. 그때만 앞 앱 창을 다시 본다
        nc.addObserver(forName: NSWorkspace.activeSpaceDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self = self, self.frontPid != 0 else { return }
            let full = isFullScreen(pid: self.frontPid)
            if full != self.frontFull { self.frontFull = full; self.emit(["type": "fullscreen", "active": full]) }
        }
        if let app = NSWorkspace.shared.frontmostApplication, app.processIdentifier != me { front(app) }
        capture.changed = { [weak self] on in self?.emit(["type": "capture", "active": on]) }
        capture.start()
        timer = Timer.scheduledTimer(withTimeInterval: IdleTracker.every, repeats: true) { [weak self] _ in self?.poll() }
        timer?.tolerance = 1.0
        Thread.detachNewThread { [weak self] in
            while let line = readLine(strippingNewline: true) {
                guard let data = line.data(using: .utf8),
                      let cmd = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                DispatchQueue.main.async { self?.onCommand?(cmd) }
            }
            DispatchQueue.main.async { NSApp.terminate(nil) }   // 파이썬 쪽이 끝났다
        }
    }

    private func front(_ app: NSRunningApplication) {
        let pid = app.processIdentifier
        let now = ProcessInfo.processInfo.systemUptime
        let justLaunched = launched[pid].map { now - $0 < 10 } ?? false
        launched = launched.filter { now - $0.value < 60 }
        frontPid = pid
        frontFull = isFullScreen(pid: pid)
        lastAxDoc = nil
        emit(["type": "front", "app": app.localizedName ?? "", "bundle": app.bundleIdentifier ?? "",
              "launched": justLaunched, "fullscreen": frontFull])
        if axTrusted { follow(pid); axFired(kAXFocusedWindowChangedNotification) }
    }

    private func poll() {
        let nowTrusted = AXIsProcessTrusted()
        if nowTrusted != axTrusted {
            axTrusted = nowTrusted
            emit(["type": "ready", "ax": axTrusted])
            if axTrusted, frontPid != 0 {
                follow(frontPid)
                axFired(kAXFocusedWindowChangedNotification)
            }
        }
        if let s = hidIdleSeconds(), idle.shouldSend(seconds: s, now: ProcessInfo.processInfo.systemUptime) {
            emit(["type": "idle", "seconds": s])
        }
    }

    fileprivate func axFired(_ name: String) {   // 마지막 알림에서 250ms 조용하면 한 번만 조회한다
        axWork?.cancel()
        let pid = axPid
        let work = DispatchWorkItem { [weak self] in
            self?.axQueue.async { self?.document(pid: pid, event: name) }
        }
        axWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + ProSensor.axDelay, execute: work)
    }

    private func follow(_ pid: pid_t) {
        if pid == axPid, axObserver != nil { return }
        if let o = axObserver {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(o), .defaultMode)
        }
        axObserver = nil
        axPid = pid
        var obs: AXObserver?
        let callback: AXObserverCallback = { _, _, name, refcon in
            guard let refcon = refcon else { return }
            Unmanaged<ProSensor>.fromOpaque(refcon).takeUnretainedValue().axFired(name as String)
        }
        guard AXObserverCreate(pid, callback, &obs) == .success, let o = obs else { return }
        let element = AXUIElementCreateApplication(pid)
        let ref = Unmanaged.passUnretained(self).toOpaque()
        for n in axNames { AXObserverAddNotification(o, element, n as CFString, ref) }
        CFRunLoopAddSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(o), .defaultMode)
        axObserver = o
    }

    private func document(pid: pid_t, event: String) {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 1.5)
        var win: CFTypeRef?
        var path: Any = NSNull()
        if AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute as CFString, &win) == .success, let w = win {
            var doc: CFTypeRef?
            if AXUIElementCopyAttributeValue(w as! AXUIElement, kAXDocumentAttribute as CFString, &doc) == .success,
               let s = doc as? String, let url = URL(string: s), url.isFileURL {
                path = url.path
            }
        }
        let docStr = path as? String
        if event == kAXTitleChangedNotification {
            guard let s = docStr, s != lastAxDoc else { return }
        }
        lastAxDoc = docStr
        let short = ["AXFocusedWindowChanged": "focused_window", "AXMainWindowChanged": "main_window",
                     "AXWindowCreated": "window_created", "AXTitleChanged": "title_changed"][event] ?? "window"
        emit(["type": "ax", "event": short, "document": path])
    }
}

var urlArg = "http://127.0.0.1:8765/"
var wanderArg = false
var miniArg = false
var proArg = false
var sensorOnlyArg = false
var noKillArg = false
let args = CommandLine.arguments
var i = 1
while i < args.count {
    if args[i] == "--url", i + 1 < args.count {
        urlArg = args[i + 1]
        i += 2
    } else if args[i] == "--wander" {
        wanderArg = true
        i += 1
    } else if args[i] == "--mini" {
        miniArg = true
        i += 1
    } else if args[i] == "--pro" {
        proArg = true
        i += 1
    } else if args[i] == "--sensor" {
        sensorOnlyArg = true
        i += 1
    } else if args[i] == "--no-kill" {
        noKillArg = true
        i += 1
    } else if args[i] == "--selftest" {
        // 앱을 띄우기 전에 끝낸다 (killOtherInstances가 떠 있는 펫을 죽이지 않게)
        exit(runCPUSelfTest() == 0 ? 0 : 1)
    } else {
        i += 1
    }
}

let app = NSApplication.shared
if sensorOnlyArg {
    app.setActivationPolicy(.accessory)
    ProSensor.shared.start()
    app.run()
} else {
    let delegate = PetAppDelegate(url: urlArg, wander: wanderArg)
    delegate.miniEdition = miniArg
    delegate.proSensor = proArg && !miniArg   // 센서는 pro일 때만. mini 플래그가 같이 오면 mini가 이긴다
    delegate.noKill = noKillArg
    app.delegate = delegate
    app.run()
}
