"""BotEngine — state machine non-blocking.

Không dùng sleep dài trong state (plan cũ sleep(32) là sai: ad 5 giây thì mất
27 giây, ad 60 giây thì tỉnh giữa video). Mỗi state có entered_at, tick kiểm
tra elapsed.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from ..config import Config, data_path

TEMPLATES_DIR = data_path("templates", ".keep").parent
from ..core import permissions
from ..core.actuator import Actuator
from ..core.capture import CaptureService
from ..core.safety import SafetyGuard
from ..perception import cheap
from ..perception.classify import _match_word, classify, keywords_for_classify
from ..perception.types import ScreenKind
from ..perception.vlm import FlorenceVLM
from ..perception.yolo import YoloDetector
from ..perception.worker import PerceptionWorker
from ..store.events import EventBus
from ..store.samples import SampleWriter
from ..store.stats import SessionStats
from .ad_closer import AdAttempt, AdCloser
from .rules import RuleEngine
from .states import TIMEOUTS, BotState
from .watchdog import Watchdog

# Khớp theo BIÊN TỪ qua _match_word, và bỏ keyword < 3 ký tự.
# "x2" từng nằm trong danh sách này và khớp bừa vào nội dung tuỳ ý.
# Số frame NO_CONTENT liên tiếp mới coi là thật (chống frame lỗi tạm thời)
NO_CONTENT_LIMIT = 8

# phash lệch quá mức này -> màn hình đã đổi kể từ lúc OCR, dữ liệu cũ không
# dùng được. Đo thật: cùng màn cách 1.2s = 0-4, khác event = 11-33.
STALE_PHASH_DIST = 8

REWARD_KEYWORDS = ["xem quảng cáo", "watch ad", "nhận thưởng", "free reward",
                   "nhân đôi", "watch video", "phần thưởng", "free gift"]


class BotEngine:
    def __init__(self, cfg: Config, bus: EventBus, capture: CaptureService):
        self.cfg = cfg
        self.bus = bus
        self.capture = capture
        self.guard = SafetyGuard(cfg.app)
        self.act = Actuator(self.guard, bus)
        self.stats = SessionStats()
        self.vlm = FlorenceVLM(cfg.ads)
        self.yolo = YoloDetector(cfg.ads)
        self.worker = PerceptionWorker()
        self.rules = RuleEngine(cfg.game, templates_dir=TEMPLATES_DIR)
        self.closer = AdCloser(cfg.ads, self.vlm, bus, yolo=self.yolo)
        self.dog = Watchdog(self.act, bus, self.stats)
        self.samples = SampleWriter(
            data_path("samples", ".keep").parent,
            enabled=bool(cfg.ads.get("collect_samples", True)))

        self.state = BotState.STOPPED
        self.entered_at = time.time()
        self.attempt: AdAttempt | None = None
        self.last_classify = None
        self._classify_at = 0.0
        self._no_content = 0
        # Luật đã thử mà không hành động được, trên CÙNG kết quả OCR hiện tại.
        # Xoá mỗi lần classify làm mới.
        self._declined: set[str] = set()
        self._perm = True
        self._perm_at = 0.0
        # phash của màn game NGAY TRƯỚC khi bấm vào quảng cáo — dùng làm bằng
        # chứng dương "đã về lại game" khi thoát AD_CLOSING.
        self._pre_ad_hash = None
        # phash của frame mà kết quả classify/OCR hiện tại được tính từ đó.
        # Dùng để phát hiện "màn hình đã đổi kể từ lúc OCR" -> dữ liệu đã cũ.
        self._classify_hash = None
        self._said_stale = False
        self._said_ad_rule = False
        # phash của màn hình LÚC VỪA VÀO quảng cáo, và cờ "đã thật sự rời khỏi
        # nó chưa". Bằng chứng "có luật tầng A khớp" đúng ở CẢ HAI phía — trước
        # khi quảng cáo kịp hiện, và sau khi đã đóng xong — nên không dùng được
        # nếu chưa biết mình đã đi khỏi màn game hay chưa.
        self._ad_entry_hash = None
        self._ad_left = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused = False
        self.tick_fps = int(cfg.get("app.engine.tick_fps", 12) or 12)
        self.session_dir: Path | None = None

    # ------------------------------------------------------------- vòng đời
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            self._paused = False
            return
        self.guard.reset()
        self.stats = SessionStats()
        self.dog.stats = self.stats
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.session_dir = data_path("sessions", ts, "events.jsonl").parent
        self.bus.open_session(self.session_dir / "events.jsonl")
        self.worker.start()
        if self.vlm.enabled:
            # lần gọi VLM đầu mất ~12s (nạp + warm-up MPS) -> làm ở nền ngay bây
            # giờ, đừng để nó rơi vào lúc gặp quảng cáo đầu tiên
            self.vlm.warm_size = 224      # xấp xỉ dải 25% (394x213)
            self.vlm.prewarm(self.bus)
        if self.yolo.enabled:
            self.yolo.prewarm(self.bus)      # 3s khởi động nguội, xem yolo.py
        self._stop.clear()
        self._paused = False
        self._goto(BotState.PREFLIGHT)
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()
        self.bus.log("info", "engine bắt đầu")

    def pause(self) -> None:
        self._paused = not self._paused
        self.bus.log("info", "tạm dừng" if self._paused else "tiếp tục")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._goto(BotState.STOPPED)
        if self.session_dir:
            self.stats.save(self.session_dir / "stats.json")
        self.bus.close_session()
        self.bus.log("info", "engine dừng")

    def kill(self) -> None:
        self.guard.kill()
        self._goto(BotState.PANIC)
        self.bus.log("error", "KILL SWITCH — về PANIC")

    # --------------------------------------------------------------- state
    def _goto(self, s: BotState, reason: str = "") -> None:
        if s is self.state:
            return
        prev = self.state
        self.stats.add_state_time(prev.value, time.time() - self.entered_at)
        self.state = s
        self.entered_at = time.time()
        if s is BotState.AD_WATCHING:
            self._ad_entry_hash = None
            self._ad_left = False
        if s is BotState.AD_CLOSING and self.attempt is None:
            self.attempt = AdAttempt()
        if s not in (BotState.AD_CLOSING, BotState.AD_WATCHING):
            self.attempt = None
        self.bus.publish({"type": "state", "from": prev.value, "to": s.value,
                          "reason": reason})

    @property
    def elapsed(self) -> float:
        return time.time() - self.entered_at

    # ---------------------------------------------------------------- loop
    def _run(self) -> None:
        period = 1.0 / max(1, self.tick_fps)
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                if not self._paused:
                    self._tick()
            except Exception as e:  # noqa: BLE001
                self.bus.log("error", f"tick lỗi: {type(e).__name__}: {e}")
            dt = time.perf_counter() - t0
            if dt < period:
                time.sleep(period - dt)

    def _perm_ok(self) -> bool:
        """Quyền Screen Recording, cache 5s (đây là syscall TCC)."""
        now = time.time()
        if now - self._perm_at > 5.0:
            self._perm_at = now
            self._perm = permissions.screen_recording()
        return self._perm

    def _need_classify(self) -> bool:
        """OCR 62ms — đừng gọi mỗi frame. Tần suất theo state."""
        gap = 2.0 if self.state in (BotState.GAME_PLAY,) else 0.8
        return (time.time() - self._classify_at) >= gap

    def _tick(self) -> None:
        self.stats.ticks += 1
        if self.guard.killed:
            self._goto(BotState.PANIC, "killed")
            return
        if self.guard.session_expired():
            self.bus.log("warn", "hết thời lượng phiên -> dừng")
            self._stop.set()
            return

        frame = self.capture.latest()
        if frame is None:
            return
        bgr, win = frame.bgr, frame.win

        # Giành focus TỪ ĐÂY, trước khi OCR và trước khi quyết định — để phần
        # mở màn cố định của mỗi hành động không nằm chen giữa "quyết định" và
        # "chuột chạm màn". Cửa chống-lệch-màn bên dưới không bắt được khoảng
        # trống đó vì nó chạy trước.
        #
        # TUYỆT ĐỐI KHÔNG `return` ở đây. Bug đã gặp thật: `is_frontmost` từng
        # đọc qua NSWorkspace và luôn trả False (xem `window.is_frontmost`), nên
        # tick nào cũng tưởng "vừa activate" -> bỏ lượt -> bot đứng im hoàn
        # toàn, mà GAME_PLAY lại là state DUY NHẤT không có timeout nên không
        # có gì kêu lên. Việc lấy focus chỉ được phép làm ảnh cũ đi, không được
        # phép chặn cả vòng lặp.
        if self.act.ensure_focus(win):
            fresh = self.capture.latest()      # ảnh cũ chụp lúc cửa sổ còn dưới
            if fresh is not None:
                bgr, win = fresh.bgr, fresh.win
            self._classify_at = 0.0            # OCR lại ngay trong tick này
            self.bus.log("info", "đã đưa cửa sổ iPhone lên trước", sys=True)

        idle = self.rules.update_idle(bgr)

        # phân loại (có OCR) theo tần suất, không phải mỗi frame
        if self._need_classify() or self.last_classify is None:
            self.last_classify = classify(
                bgr, ad_keywords=keywords_for_classify(self.cfg.ads),
                ad_icon=self.cfg.ads,
                permission_ok=self._perm_ok())
            self._classify_at = time.time()
            self._classify_hash = cheap.phash(bgr)
            self._declined.clear()
            self._said_stale = False
            self._said_ad_rule = False
            self.bus.publish({"type": "classify",
                              "kind": self.last_classify.kind.value,
                              "reason": self.last_classify.reason,
                              "hf": round(self.last_classify.hf, 2),
                              "texts": len(self.last_classify.texts)})
        res = self.last_classify

        # NO_CONTENT có thể là frame lỗi TẠM THỜI, không phải thiếu quyền:
        # lúc user di chuyển cửa sổ iPhone Mirroring, CGWindowListCreateImage
        # trả frame rỗng/chưa composite. Đã gặp thật (cửa sổ dịch 1029→1027).
        # Một frame lỗi không được phép dừng cả bot.
        if res.kind is ScreenKind.NO_CONTENT:
            self._no_content += 1
            if self._no_content == 1:
                self.bus.log("warn", f"frame không có nội dung ({res.reason})")
            if self._no_content >= NO_CONTENT_LIMIT:
                self.bus.log("error", f"{NO_CONTENT_LIMIT} frame liên tiếp không có "
                                      f"nội dung -> dừng. {res.reason}")
                self._stop.set()
            return
        self._no_content = 0

        # watchdog có quyền cướp state
        in_ad = self.state in (BotState.AD_WATCHING, BotState.AD_CLOSING)
        if in_ad and res.kind is ScreenKind.APPSTORE:
            handled = None      # trang cài app trong quảng cáo là bình thường
        else:
            handled = self.dog.handle(res, win, bgr)
        if handled:
            self._goto(BotState.DISCONNECTED if handled == "pause"
                       else BotState.SYNC, f"watchdog:{handled}")
            return

        st = self.state
        if st in (BotState.PREFLIGHT, BotState.SYNC, BotState.DISCONNECTED):
            self._state_sync(res, win, bgr)
        elif st is BotState.HOME_SCREEN:
            self._state_home(res, win, bgr)
        elif st is BotState.GAME_PLAY:
            self._state_game(res, win, bgr, idle)
        elif st is BotState.REWARD_PROMPT:
            self._state_reward(res, win, bgr)
        elif st is BotState.AD_WATCHING:
            self._state_ad_watching(res, win, bgr)
        elif st is BotState.AD_CLOSING:
            self._state_ad_closing(res, win, bgr)
        elif st is BotState.AD_ESCAPED:
            self.act.home_gesture(win, label="quay lại từ App Store")
            self._goto(BotState.SYNC)
        elif st is BotState.STUCK:
            self._state_stuck(res, win, bgr)

        # timeout chung
        limit = TIMEOUTS.get(self.state)
        if limit and self.elapsed > limit and self.state not in (
                BotState.STUCK, BotState.PANIC):
            self._goto(BotState.STUCK, f"timeout {limit}s ở {self.state.value}")

    # ------------------------------------------------------------- handlers
    def _state_sync(self, res, win, bgr) -> None:
        if self.state is BotState.PREFLIGHT:
            p = permissions.check()
            if not p["ok"]:
                self.bus.log("error", "thiếu quyền:\n" + p["hint"])
                self._stop.set()
                return
        mapping = {
            ScreenKind.GAME: BotState.GAME_PLAY,
            ScreenKind.AD: BotState.AD_WATCHING,
            ScreenKind.HOME: BotState.HOME_SCREEN,
            ScreenKind.APPSTORE: BotState.AD_ESCAPED,
        }
        nxt = mapping.get(res.kind)
        # Cùng lý do như trong `_state_game`: có luật tầng A khớp thì đây là màn
        # game, dù classify nói AD. Bấm Start ngay trên màn rương vàng cuối lượt
        # từng đưa thẳng bot vào AD_WATCHING (phiên data/sessions/20260830-050446).
        if nxt is BotState.AD_WATCHING:
            low = " | ".join(t.text.lower() for t in res.texts)
            if self._rule_signature(bgr, low, res.texts) is not None:
                nxt = BotState.GAME_PLAY
        if nxt:
            self.guard.clear_stuck()
            self._goto(nxt, f"sync -> {res.kind.value}")

    def _state_home(self, res, win, bgr) -> None:
        if self.dog.open_game(res, win, bgr):
            self._goto(BotState.SYNC, "đã tap icon game")

    def _rule_signature(self, bgr, low: str, res_texts=None):
        """Có luật tầng A nào khớp không — luật chính là CHỮ KÝ của màn game.

        `classify` chỉ có tín hiệu yếu (keyword sát mép, dấu ✕ sát mép) nên nó
        nhận nhầm màn game có nút ở đáy là quảng cáo. Luật do người dùng khai
        báo cho ĐÚNG một màn game là bằng chứng mạnh hơn hẳn.
        `_state_ad_closing` đã dùng đúng bằng chứng này để kết luận "đã về
        game"; `_state_game` phải nhất quán, nếu không hai chỗ đá nhau thành
        vòng lặp (đã xảy ra thật, xem `classify_keywords` trong config/ads.toml).

        Luật ĐANG TẮT không tính, và luật đã thử-mà-không-làm-được trên chính
        kết quả OCR này (`_declined`) cũng không tính: bằng chứng phải là thứ
        engine thật sự hành động được, nếu không bot đứng im trong GAME_PLAY —
        state duy nhất KHÔNG có timeout.
        """
        return self.rules.evaluate(bgr, 0.0, low, ignore_cooldown=True,
                                   skip=set(self._declined), texts=res_texts)

    def _state_game(self, res, win, bgr, idle) -> None:
        h, w = bgr.shape[:2]
        low = " | ".join(t.text.lower() for t in res.texts)
        if res.kind is ScreenKind.AD:
            sig = self._rule_signature(bgr, low, res.texts)
            if sig is None:
                self.stats.ads_seen += 1
                self._goto(BotState.AD_WATCHING, "phát hiện quảng cáo")
                return
            if not self._said_ad_rule:
                self._said_ad_rule = True
                self.bus.log("info", f"classify ra AD ({res.reason}) nhưng luật "
                                     f"{sig[0].name!r} khớp -> coi là màn game",
                             sys=True)
        if _match_word(low, REWARD_KEYWORDS):
            self._goto(BotState.REWARD_PROMPT, "thấy nút xem quảng cáo")
            return

        # CHỐNG RACE: quyết định phải dựa trên OCR của ĐÚNG màn hình đang hiện.
        # Bug đã gặp: bot swipe trái liên tục qua chuỗi màn gear (SOLARIUS SET,
        # PVP RAID...). Một event MỚI xuất hiện nhưng classify chỉ làm mới mỗi
        # 2s, nên luật cũ vẫn khớp trên dữ liệu cũ và swipe chạy sai màn.
        # Đo thật: phash cùng màn cách 1.2s = 0-4, khác event = 11-33.
        newest = self.capture.latest()
        if newest is not None and self._classify_hash is not None:
            dist = cheap.phash_distance(cheap.phash(newest.bgr), self._classify_hash)
            if dist > STALE_PHASH_DIST:
                self._classify_at = 0.0          # buộc OCR lại ngay tick sau
                if not self._said_stale:
                    self._said_stale = True
                    self.bus.log("info", f"màn hình đã đổi kể từ lúc OCR "
                                         f"(phash lệch {dist}) -> OCR lại, "
                                         f"bỏ lượt hành động", sys=True)
                return

        # Thử lần lượt: luật nào khớp nhưng không hành động được thì bỏ qua và
        # cho luật tiếp theo cơ hội, thay vì ăn mất lượt.
        skip: set[str] = set(self._declined)
        for _ in range(6):
            hit = self.rules.evaluate(bgr, idle, low, skip=skip,
                                      texts=res.texts)
            if not hit:
                return
            if self._apply_rule(hit[0], res, win, bgr, w, h):
                if hit[0].enters_ad:
                    self.stats.ads_seen += 1
                    self._pre_ad_hash = cheap.phash(bgr)
                    # Không thể dựa vào classify: quảng cáo video mấy chục giây
                    # đầu KHÔNG có nút đóng nào, nên không có dấu hiệu nào để
                    # nhận ra "đang ở quảng cáo". Luật tự khai báo là chắc nhất.
                    self._goto(BotState.AD_WATCHING,
                               f"luật {hit[0].name!r} khai báo enters_ad")
                return
            skip.add(hit[0].name)
            self._declined.add(hit[0].name)

    def _apply_rule(self, rule, res, win, bgr, w, h) -> bool:
        """Thực hiện một luật. Trả False nếu không hành động được -> thử luật khác."""
        do = rule.do
        action = do.get("action", "tap")
        fid = self.capture.latest().id if self.capture.latest() else None

        # tap_text: tìm chữ bằng OCR rồi tap vào đó (có thể lệch theo dy).
        tap_text_rel = None
        if action == "tap_text":
            needle = str(do.get("text", "")).lower().strip()
            box = next((t for t in res.texts
                        if needle and needle in t.text.lower().strip()), None)
            if box is None:
                self.bus.log("info", f"luật {rule.name!r}: OCR không thấy chữ "
                                     f"{needle!r} -> thử luật khác", sys=True)
                return False
            tap_text_rel = (box.cx / w,
                            box.cy / h + float(do.get("dy", 0.0)))
            tap_text_rel = (min(1.0, max(0.0, tap_text_rel[0])),
                            min(1.0, max(0.0, tap_text_rel[1])))

        if action == "tap":
            if self.act.tap(tuple(do.get("at", [0.5, 0.5])), win,
                            source="rule", label=rule.name, frame_id=fid):
                self.stats.taps += 1
        elif action == "tap_text":
            if self.act.tap(tap_text_rel, win, source="rule",
                            label=f"{rule.name} [chữ {do.get('text')!r}]",
                            hold_ms=int(do.get("hold_ms", 80)), frame_id=fid):
                self.stats.taps += 1
        elif action == "swipe":
            if self.act.swipe(tuple(do.get("from", [0.8, 0.5])),
                              tuple(do.get("to", [0.2, 0.5])), win,
                              duration_ms=int(do.get("duration_ms", 220)),
                              steps=int(do.get("steps", 18)),
                              hold_end_ms=int(do.get("hold_end_ms", 80)),
                              source="rule", label=rule.name, frame_id=fid):
                self.stats.swipes += 1
        elif action == "hold":
            self.act.hold(tuple(do.get("at", [0.5, 0.5])), win,
                          ms=int(do.get("ms", 200)), source="rule",
                          label=rule.name, frame_id=fid)
        self.rules.note_fired(rule)
        self.rules.reset_idle()
        # Buộc OCR lại ở tick sau: màn hình vừa bị tác động, dữ liệu classify
        # hiện tại đã lỗi thời.
        self._classify_at = 0.0
        return True

    def _state_reward(self, res, win, bgr) -> None:
        h, w = bgr.shape[:2]
        for t in res.texts:
            if _match_word(t.text.lower().strip(), REWARD_KEYWORDS):
                if self.act.tap((t.cx / w, t.cy / h), win, source="rule",
                                label="bấm nhận thưởng quảng cáo"):
                    self.stats.taps += 1
                self.stats.ads_seen += 1
                self._goto(BotState.AD_WATCHING, "đã bấm nhận thưởng")
                return
        self._goto(BotState.GAME_PLAY, "không còn thấy nút thưởng")

    def _back_to_game(self, res, bgr) -> str | None:
        """Bằng chứng DƯƠNG là đã về lại màn game, hoặc None.

        `classify == GAME` KHÔNG đủ: nó chỉ là nhánh mặc định "không khớp màn
        hệ thống nào", nên một frame quảng cáo lạ cũng ra GAME. Ba bằng chứng:
          1. đang ở Home Screen
          2. có luật tầng A nào khớp -> luật chính là chữ ký của màn game
          3. phash khớp màn ngay trước khi bấm vào quảng cáo

        Dùng chung cho AD_WATCHING và AD_CLOSING — hai chỗ dùng hai tiêu chuẩn
        khác nhau là công thức tạo vòng lặp (đã xảy ra thật).
        """
        if res.kind is ScreenKind.HOME:
            return "về Home Screen"
        low = " | ".join(t.text.lower() for t in res.texts)
        if self.rules.evaluate(bgr, 0.0, low, ignore_enabled=True,
                               ignore_cooldown=True,
                               texts=res.texts) is not None:
            return "có luật tầng A khớp"
        if self._pre_ad_hash is not None:
            d = cheap.phash_distance(cheap.phash(bgr), self._pre_ad_hash)
            if d <= 6:
                return f"phash khớp màn trước quảng cáo (d={d})"
        return None

    def _state_ad_watching(self, res, win, bgr) -> None:
        """Ngồi xem cho hết quảng cáo. `min_watch_seconds` là TRẦN, không phải
        giấc ngủ cố định — về tới màn game thì ra ngay.

        Vì sao trần phải dài: bug đã gặp (phiên data/sessions/20260830-081318).
        Chờ đúng 5 giây rồi vào quét trong khi quảng cáo còn ĐANG TẢI (OCR đọc
        được 4 chữ). Bước 3 tap ứng viên VLM ở rel (0.906,0.150) -> mở thẳng
        App Store, kẹt 45 giây, phải escalate + 5 cú vuốt Home mới thoát. Một
        cú tap sớm tốn 60 giây.

        Nhiều quảng cáo hiện nút đóng NGAY nhưng đang tắt, quanh nó là vòng
        tròn đếm thời gian — vòng tròn đó là đồ hoạ, `countdown_left()` đọc chữ
        nên không thấy. Chờ đủ lâu là cách duy nhất hiện có để không tap vào nó.
        """
        # BƯỚC ĐẦU TIÊN: đã thật sự rời màn game chưa?
        # Bug đã gặp (phiên 20260830-111459): luật `enters_ad` bắn lúc 6.3s,
        # 0.2 giây sau bot đã tự kết luận "quảng cáo đã đóng" và về GAME_PLAY —
        # trong khi quảng cáo còn chưa kịp tải, màn hình vẫn là dialog cũ nên
        # chính cái luật vừa mở quảng cáo lại thành bằng chứng "đã về game".
        # Quảng cáo hiện lên sau đó, `classify` trả GAME (playable không có ✕,
        # không keyword) nên không còn đường nào quay lại AD_CLOSING. Bot đứng
        # im 187 giây.
        # `classify` nói AD là ĐÃ ĐỦ — khỏi cần chờ màn hình đổi.
        # Bug đã gặp (phiên 20260830-154455): quảng cáo end-card nền đen, ảnh
        # TĨNH, có ✕ rõ ở (372,126). Vào AD_WATCHING vì classify ra AD, nhưng
        # phash không bao giờ đổi -> cửa grace bên dưới kết luận "không có
        # quảng cáo nào" -> về GAME_PLAY -> classify lại ra AD -> vào lại.
        # Vòng lặp 5 giây/lần, không bao giờ tới AD_CLOSING (cần 8s) nên không
        # bao giờ tap. Grace chỉ dành cho ca vào bằng luật `enters_ad` mà quảng
        # cáo không hiện ra.
        if res.kind is ScreenKind.AD:
            self._ad_left = True
        if self._ad_entry_hash is None:
            self._ad_entry_hash = cheap.phash(bgr)
        if not self._ad_left:
            d = cheap.phash_distance(cheap.phash(bgr), self._ad_entry_hash)
            if d > STALE_PHASH_DIST:
                self._ad_left = True
            else:
                # Màn hình y nguyên sau ngần này giây -> chẳng có quảng cáo nào
                # hiện ra, luật `enters_ad` báo nhầm. Về game, đừng chờ hết trần.
                cho = float(self.cfg.ads.get("no_ad_grace_s", 5.0))
                if self.elapsed >= cho:
                    self._goto(BotState.GAME_PLAY,
                               f"chờ {cho:.0f}s mà màn hình không đổi -> "
                               f"không có quảng cáo nào")
                return

        back = self._back_to_game(res, bgr)
        if back:
            self.stats.note_close("step0")
            self.guard.clear_stuck()
            self._goto(BotState.GAME_PLAY, f"quảng cáo đã đóng khi đang xem: {back}")
            return
        min_watch = float(self.cfg.ads.get("min_watch_seconds", 5.0))
        if self.elapsed >= min_watch:
            self._goto(BotState.AD_CLOSING, f"đã xem đủ {min_watch:.0f}s")

    def _note_tap(self, a, bgr, c, step: str, label: str) -> None:
        """Nhớ cú tap vừa bắn, kèm frame NGAY TRƯỚC lúc tap.

        Phải copy frame: sau cú tap màn hình đổi, lúc đó chụp lại là muộn — mà
        đúng tấm ảnh "trước khi tap" mới là mẫu huấn luyện cần.
        """
        a.pending = {
            "bgr": bgr.copy(),
            "box": {"cx": c.cx, "cy": c.cy, "w": c.w, "h": c.h},
            "origin": c.origin or "?",
            "label": label,
            "step": step,
            "at": time.time(),
            "phash": cheap.phash(bgr),
        }

    def _confirm_tap(self, a, bgr, back: str | None) -> None:
        """Cú tap vừa rồi có ăn không — ĐO, không suy đoán.

        `closed_by_step` chỉ ghi "lúc phát hiện đã về game thì đang ở bước mấy",
        nên quảng cáo tự tắt trong lúc VLM chạy 0.6s cũng được tính cho VLM. Vì
        thế con số "bước 3 đóng được 7 lần" không chứng minh được điều gì.

        Ba kết cục:
          hit     — về được màn game trong cửa sổ chờ -> chỗ đó ĐÚNG là nút đóng
          miss    — hết cửa sổ mà màn hình y nguyên   -> chỗ đó KHÔNG phải
          (bỏ)    — màn hình có đổi nhưng vẫn ở quảng cáo: không kết luận được,
                    có thể do chính quảng cáo chuyển cảnh. Không ghi mẫu.

        `hit` là bằng chứng gián tiếp — quảng cáo tự tắt đúng lúc cũng ra `hit`.
        Cửa sổ ngắn nên hiếm, nhưng đừng coi tập mẫu này là nhãn vàng.
        """
        p = a.pending
        if p is None:
            return
        cho = float(self.cfg.ads.get("confirm_delay_s", 1.2))
        if back:
            ket = "hit"
        elif time.time() - p["at"] < cho:
            return                       # chưa tới lúc kết luận
        else:
            d = cheap.phash_distance(cheap.phash(bgr), p["phash"])
            ket = "miss" if d <= 3 else None
        a.pending = None
        if ket is None:
            return
        self.stats.note_tap(p["origin"], ket == "hit")
        ten = self.samples.record(
            p["bgr"], p["box"], ket,
            meta={"origin": p["origin"], "step": p["step"], "label": p["label"]})
        self.bus.log("info",
                     f"tap {p['origin']} @({p['box']['cx']:.0f},{p['box']['cy']:.0f})"
                     f" -> {'TRÚNG' if ket == 'hit' else 'trượt'}"
                     + (f" · mẫu {ten}" if ten else ""))

    def _state_ad_closing(self, res, win, bgr) -> None:
        a = self.attempt
        if a is None:
            self.attempt = a = AdAttempt()
        h, w = bgr.shape[:2]
        interval = float(self.cfg.ads.get("rescan_interval_s", 2.0))
        max_s = float(self.cfg.ads.get("rescan_max_s", 45.0))

        # KHÔNG thoát khi thấy APPSTORE: trang cài app là một phần của quảng
        # cáo, cứ quét tìm nút đóng tiếp. Chỉ coi là xong khi thấy lại màn game.
        back = self._back_to_game(res, bgr)
        # Xác nhận TRƯỚC khi thoát: `_goto` rời AD_CLOSING sẽ vứt `attempt`,
        # mà cú tap đang chờ nằm trong đó.
        self._confirm_tap(a, bgr, back)
        if back:
            self.stats.note_close(f"step{a.step}")
            self.guard.clear_stuck()
            self.bus.log("info", f"đóng được quảng cáo ở bước {a.step} — {back}")
            self._goto(BotState.GAME_PLAY, f"quảng cáo đã đóng: {back}")
            return
        fid = self.capture.latest().id if self.capture.latest() else None

        # (1) Dialog "Close Video? — You will lose your reward" đã hiện.
        # Bấm RESUME VIDEO để giữ phần thưởng. KHÔNG đi qua cửa hình học vì nút
        # nằm giữa màn — đây là hành động có chủ đích trên dialog đã nhận diện.
        btn = self.closer.resume_button(res.texts)
        if btn is not None:
            self.act.tap((btn.cx / w, btn.cy / h), win, source="ad_step",
                         label=f"dialog Close Video -> tap {btn.text!r}",
                         frame_id=fid)
            a.last_scan = time.time()
            return

        # (2) Đang đếm ngược phần thưởng -> TUYỆT ĐỐI không tap nút đóng.
        # Có TRẦN tổng thời gian chờ: nếu không thì một chuỗi chữ tồn tại suốt
        # quảng cáo (ví dụ "Ad 2 of 2") sẽ đẩy mốc quét đi vô hạn và bot không
        # bao giờ tap. Đã xảy ra thật.
        now = time.time()
        max_wait = float(self.cfg.ads.get("countdown_max_wait_s", 75.0))
        left = self.closer.countdown_left(res.texts)
        if left is not None and a.waiting_s < max_wait:
            if a.wait_tick:
                a.waiting_s += now - a.wait_tick     # cộng thời gian chờ THẬT
            a.wait_tick = now
            a.wait_until = now + left
            mark = f"{left:.0f}"
            if a.said_wait != mark:
                a.said_wait = mark
                self.bus.log("info", f"đang đếm ngược thưởng, chờ {left:.0f}s "
                                     f"rồi mới tìm nút đóng "
                                     f"(đã chờ {a.waiting_s:.0f}s)")
            return
        if left is not None and a.said_wait != "TRAN":
            a.said_wait = "TRAN"
            self.bus.log("warn", f"đã chờ đếm ngược {a.waiting_s:.0f}s vượt trần "
                                 f"{max_wait:.0f}s -> quét nút đóng luôn")
        a.wait_tick = 0.0

        if now < a.wait_until:
            return
        if now - a.last_scan < interval:
            return
        a.last_scan = now

        # Các bước tìm nút, xếp theo ĐỘ TIN CẬY giảm dần. Tầng nào ra ứng viên
        # dùng được thì tap rồi dừng.
        #
        # QUAN TRỌNG: tầng nào có ứng viên nhưng đang trong cửa `retry_after_s`
        # thì DỪNG luôn, không rơi xuống tầng yếu hơn. "Đang chờ tap lại" khác
        # hẳn "không tìm thấy" — chờ thì phải chờ, chứ đi thử thứ kém tin cậy
        # hơn là đi ngược.
        #
        # Bug đã gặp (phiên 20260830-170024, kẹt 60 giây trên sheet App Store):
        #   2b tìm đúng ✕ ở (46,145) -> tap -> điểm đó vào cooldown 15s
        #   chu kỳ sau: 2b bị bỏ qua -> RƠI XUỐNG tầng 3
        #   tầng 3 tap 'circle button' (364,145) = nút SHARE -> mở sheet chia sẻ
        #   chu kỳ sau: 2b tap ✕ -> đóng sheet chia sẻ, về lại App Store
        #   ✕ lại vào cooldown -> lại rơi xuống tầng 3 -> lại tap share...
        def thu(cands, buoc: str, nhan) -> str:
            """'tap' | 'cho' (có ứng viên nhưng đang chờ tap lại) | 'khong'."""
            co = False
            for c in cands:
                rel = (c.cx / w, c.cy / h)
                if self.closer.already_tried(a, rel):
                    co = True
                    continue
                a.tried_points.append((*rel, time.time()))
                self._note_tap(a, bgr, c, buoc, nhan(c))
                self.act.tap(rel, win, source="ad_step",
                             label=f"bước {buoc} {nhan(c)}", frame_id=fid)
                return "tap"
            return "cho" if co else "khong"

        # --- bước 2: OCR keyword ---
        a.step = 2
        kq = thu(self.closer.step_ocr(bgr, res.texts), "2",
                 lambda c: f"OCR '{c.label}'")
        if kq != "khong":
            return

        # --- bước 2b: dò dấu ✕ bằng OpenCV, quét cả frame, < 5ms ---
        a.step = 22       # 22 = "bước 2b" trong thống kê closed_by_step
        kq = thu(self.closer.step_icon(bgr, res.texts), "2b",
                 lambda c: f"✕ {c.origin} điểm={c.score}")
        if kq != "khong":
            return

        # --- bước 2c: detector tự train, cả frame, ~20ms ---
        # Đứng TRƯỚC tầng C vì rẻ hơn 30 lần. Chưa có model thì trả rỗng và rơi
        # thẳng xuống dưới, pipeline chạy y như trước.
        a.step = 23       # 23 = "bước 2c" trong thống kê closed_by_step
        kq = thu(self.closer.step_yolo(bgr, res.texts), "2c",
                 lambda c: f"YOLO '{c.label}' {c.score:.2f}")
        if kq != "khong":
            return

        # --- bước 3: VLM trên DẢI 25% TRÊN CÙNG (không còn quét 4 góc) ---
        if self.vlm.enabled:
            a.step = 3
            job = self.worker.run_sync(
                lambda: self.closer.step_vlm_top(bgr, res.texts),
                name="vlm:top", timeout=25.0)
            if job.error:
                self.bus.log("warn", f"VLM lỗi: {job.error}")
                return
            if thu(job.result or [], "3",
                   lambda c: f"VLM dải trên ({job.ms:.0f}ms)") != "khong":
                return

        # --- bước 4: quét lại tới hết thời gian ---
        if a.scanning_elapsed() < max_s:
            a.step = 4
            return

        # --- bước 5: escalate ---
        # Blind tap (6 điểm đoán) đã bỏ: đo trên 57 phiên, nó đóng được đúng
        # 1/45 lần, đổi lại là 6 cú tap mù vào màn quảng cáo. Hết giờ quét thì
        # về Home luôn, đừng bắn bừa.
        a.step = 5
        self.stats.ads_failed += 1
        # MẪU QUÝ NHẤT: quảng cáo mà cả ba tầng đều bó tay. Phải lưu ĐÚNG LÚC
        # NÀY — ngay sau đây là gesture Home, màn hình đó biến mất và không
        # chụp lại được. Chờ người dùng tự bấm chụp thì gần như luôn muộn.
        # Không có khung: theo định nghĩa bot không biết nút nằm đâu, nên đây
        # là loại mẫu duy nhất phải khoanh tay.
        ten = self.samples.record(
            bgr, None, "fail",
            meta={"tried": [[round(x, 4), round(y, 4)] for x, y, _ in a.tried_points],
                  "scanning_s": round(a.scanning_elapsed(), 1),
                  "vlm": bool(self.vlm.enabled)})
        self.bus.log("warn", "không đóng được quảng cáo -> escalate về Home"
                             + (f" · mẫu khó {ten}" if ten else ""))
        self.act.home_gesture(win, label="bước 5 escalate")
        self._goto(BotState.SYNC, "escalate")

    def _state_stuck(self, res, win, bgr) -> None:
        self.stats.stuck += 1
        if self.guard.note_stuck():
            self.bus.log("error", "STUCK quá nhiều lần liên tiếp -> dừng")
            self._stop.set()
            return
        self.bus.log("warn", "STUCK -> tap vùng an toàn rồi sync lại")
        self.act.tap((0.5, 0.55), win, source="watchdog", label="safe tap")
        self._goto(BotState.SYNC, "sau escalate stuck")

    # ---------------------------------------------------------------- state
    def snapshot(self) -> dict:
        f = self.capture.latest()
        return {
            "state": self.state.value,
            "state_seconds": round(self.elapsed, 1),
            "running": self.running,
            "paused": self._paused,
            "killed": self.guard.killed,
            "capture_fps": round(self.capture.measured_fps, 1),
            "capture_grab_ms": round(self.capture.grab_ms, 1),
            "capture_idle": not (self.capture.demand() if self.capture.demand else True),
            "capture_error": self.capture.last_error,
            "window": (dict(id=f.win.id, name=f.win.name, x=f.win.x, y=f.win.y,
                            w=f.win.w, h=f.win.h) if f else None),
            "frame_id": f.id if f else None,
            "taps_per_min": self.guard.taps_per_min(),
            "samples": self.samples.written,
            "classify": (dict(kind=self.last_classify.kind.value,
                              reason=self.last_classify.reason,
                              hf=round(self.last_classify.hf, 2))
                         if self.last_classify else None),
            "vlm": self.vlm.info(),
            "yolo": self.yolo.info(),
            "stats": self.stats.to_dict(),
            "ad_step": (self.attempt.step if self.attempt else None),
        }
