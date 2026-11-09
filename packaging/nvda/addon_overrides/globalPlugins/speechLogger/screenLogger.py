# Workday Lens mouse action and screenshot capture support.
#
# This module is intentionally isolated from the speech logger plumbing so the
# low-level mouse hook stays small and easy to stop cleanly.

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
import queue
import threading
import time

from logHandler import log


WH_MOUSE_LL = 14
HC_ACTION = 0

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E

WHEEL_DELTA = 120

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000

CURSOR_SHOWING = 0x00000001
DI_NORMAL = 0x0003

LLMHF_INJECTED = 0x00000001
LLMHF_LOWER_IL_INJECTED = 0x00000002

CLICK_DOWN_MESSAGES = {
	WM_LBUTTONDOWN,
	WM_RBUTTONDOWN,
	WM_MBUTTONDOWN,
}
CLICK_UP_MESSAGES = {
	WM_LBUTTONUP,
	WM_RBUTTONUP,
	WM_MBUTTONUP,
}
WHEEL_MESSAGES = {
	WM_MOUSEWHEEL,
	WM_MOUSEHWHEEL,
}
MOUSE_ACTION_MESSAGES = CLICK_DOWN_MESSAGES | CLICK_UP_MESSAGES | WHEEL_MESSAGES

BUTTON_MESSAGES = {
	WM_LBUTTONDOWN: ("left", "down", "leftDown"),
	WM_LBUTTONUP: ("left", "up", "leftUp"),
	WM_RBUTTONDOWN: ("right", "down", "rightDown"),
	WM_RBUTTONUP: ("right", "up", "rightUp"),
	WM_MBUTTONDOWN: ("middle", "down", "middleDown"),
	WM_MBUTTONUP: ("middle", "up", "middleUp"),
}


class POINT(ctypes.Structure):
	_fields_ = [
		("x", wintypes.LONG),
		("y", wintypes.LONG),
	]


class MSLLHOOKSTRUCT(ctypes.Structure):
	_fields_ = [
		("pt", POINT),
		("mouseData", wintypes.DWORD),
		("flags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", wintypes.WPARAM),
	]


class CURSORINFO(ctypes.Structure):
	_fields_ = [
		("cbSize", wintypes.DWORD),
		("flags", wintypes.DWORD),
		("hCursor", wintypes.HANDLE),
		("ptScreenPos", POINT),
	]


class ICONINFO(ctypes.Structure):
	_fields_ = [
		("fIcon", wintypes.BOOL),
		("xHotspot", wintypes.DWORD),
		("yHotspot", wintypes.DWORD),
		("hbmMask", wintypes.HANDLE),
		("hbmColor", wintypes.HANDLE),
	]


class GUID(ctypes.Structure):
	_fields_ = [
		("Data1", wintypes.DWORD),
		("Data2", wintypes.WORD),
		("Data3", wintypes.WORD),
		("Data4", ctypes.c_ubyte * 8),
	]


class GdiplusStartupInput(ctypes.Structure):
	_fields_ = [
		("GdiplusVersion", wintypes.UINT),
		("DebugEventCallback", ctypes.c_void_p),
		("SuppressBackgroundThread", wintypes.BOOL),
		("SuppressExternalCodecs", wintypes.BOOL),
	]


class EncoderParameter(ctypes.Structure):
	_fields_ = [
		("Guid", GUID),
		("NumberOfValues", wintypes.ULONG),
		("Type", wintypes.ULONG),
		("Value", ctypes.c_void_p),
	]


class EncoderParameters(ctypes.Structure):
	_fields_ = [
		("Count", wintypes.UINT),
		("Parameter", EncoderParameter * 1),
	]


HOOKPROC = ctypes.WINFUNCTYPE(
	wintypes.LPARAM,
	ctypes.c_int,
	wintypes.WPARAM,
	wintypes.LPARAM,
)


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
gdiplus = ctypes.WinDLL("gdiplus", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

user32.SetWindowsHookExW.argtypes = [
	ctypes.c_int,
	HOOKPROC,
	wintypes.HANDLE,
	wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = wintypes.HANDLE

user32.CallNextHookEx.argtypes = [
	wintypes.HANDLE,
	ctypes.c_int,
	wintypes.WPARAM,
	wintypes.LPARAM,
]
user32.CallNextHookEx.restype = wintypes.LPARAM

user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.GetDoubleClickTime.argtypes = []
user32.GetDoubleClickTime.restype = wintypes.UINT

user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetCursorInfo.restype = wintypes.BOOL

user32.GetIconInfo.argtypes = [
	wintypes.HANDLE,
	ctypes.POINTER(ICONINFO),
]
user32.GetIconInfo.restype = wintypes.BOOL

user32.DrawIconEx.argtypes = [
	wintypes.HDC,
	ctypes.c_int,
	ctypes.c_int,
	wintypes.HANDLE,
	ctypes.c_int,
	ctypes.c_int,
	wintypes.UINT,
	wintypes.HANDLE,
	wintypes.UINT,
]
user32.DrawIconEx.restype = wintypes.BOOL

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC

user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

gdi32.CreateCompatibleBitmap.argtypes = [
	wintypes.HDC,
	ctypes.c_int,
	ctypes.c_int,
]
gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE

gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE

gdi32.BitBlt.argtypes = [
	wintypes.HDC,
	ctypes.c_int,
	ctypes.c_int,
	ctypes.c_int,
	ctypes.c_int,
	wintypes.HDC,
	ctypes.c_int,
	ctypes.c_int,
	wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL

gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteObject.restype = wintypes.BOOL

gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HANDLE

gdiplus.GdiplusStartup.argtypes = [
	ctypes.POINTER(ctypes.c_void_p),
	ctypes.POINTER(GdiplusStartupInput),
	ctypes.c_void_p,
]
gdiplus.GdiplusStartup.restype = ctypes.c_int

gdiplus.GdiplusShutdown.argtypes = [ctypes.c_void_p]
gdiplus.GdiplusShutdown.restype = None

gdiplus.GdipCreateBitmapFromHBITMAP.argtypes = [
	wintypes.HANDLE,
	wintypes.HANDLE,
	ctypes.POINTER(ctypes.c_void_p),
]
gdiplus.GdipCreateBitmapFromHBITMAP.restype = ctypes.c_int

gdiplus.GdipSaveImageToFile.argtypes = [
	ctypes.c_void_p,
	wintypes.LPCWSTR,
	ctypes.POINTER(GUID),
	ctypes.c_void_p,
]
gdiplus.GdipSaveImageToFile.restype = ctypes.c_int

gdiplus.GdipDisposeImage.argtypes = [ctypes.c_void_p]
gdiplus.GdipDisposeImage.restype = ctypes.c_int

ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
ole32.CLSIDFromString.restype = ctypes.c_long


def _guid_from_string(value):
	guid = GUID()
	hr = ole32.CLSIDFromString(value, ctypes.byref(guid))
	if hr != 0:
		raise ctypes.WinError(ctypes.get_last_error())
	return guid


JPEG_ENCODER_CLSID = _guid_from_string("{557cf401-1a04-11d3-9a73-0000f81ef32e}")
ENCODER_QUALITY_GUID = _guid_from_string("{1d5be4b5-fa4a-452d-9cdd-5db35105e7eb}")
ENCODER_PARAMETER_VALUE_TYPE_LONG = 4


def _signed_hiword(value):
	hi = (value >> 16) & 0xFFFF
	if hi >= 0x8000:
		hi -= 0x10000
	return hi


def _utc_now():
	return datetime.now(timezone.utc)


def _utc_iso(value):
	return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _default_capture_root():
	override = os.environ.get("WFHS_SCREEN_CAPTURE_DIR", "").strip()
	if override:
		return override
	base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.getcwd()
	return os.path.join(base, "WorkdayLens", "ScreenCaptures")


class MouseActionLogger:
	def __init__(
			self,
			sendEvent,
			screenshotsEnabled,
			scrollScreenshotsEnabled,
			captureRoot=None,
			clickDuplicateSuppressMs=None,
			scrollStopDelayMs=650,
			jpegQuality=60
	):
		self._sendEvent = sendEvent
		self._screenshotsEnabled = screenshotsEnabled
		self._scrollScreenshotsEnabled = scrollScreenshotsEnabled
		self.captureRoot = captureRoot or _default_capture_root()
		self.clickDuplicateSuppressMs = int(clickDuplicateSuppressMs or self._systemDoubleClickTimeMs())
		self.scrollStopDelayMs = int(scrollStopDelayMs)
		self.clickDuplicateMaxDistanceX = max(4, int(user32.GetSystemMetrics(SM_CXDOUBLECLK)))
		self.clickDuplicateMaxDistanceY = max(4, int(user32.GetSystemMetrics(SM_CYDOUBLECLK)))
		self.jpegQuality = max(1, min(100, int(jpegQuality)))

		self._queue = queue.Queue(maxsize=256)
		self._stopEvent = threading.Event()
		self._eventCounterLock = threading.Lock()
		self._scrollLock = threading.Lock()
		self._scrollTimer = None
		self._lastScrollRecord = None
		self._workerThread = None
		self._hook = None
		self._hookProcRef = None
		self._gdiplusToken = ctypes.c_void_p()
		self._gdiplusStarted = False
		self._lastCapturedClickDown = None
		self._eventCounter = 0

	def _systemDoubleClickTimeMs(self):
		try:
			return int(user32.GetDoubleClickTime())
		except Exception:
			return 500

	def start(self):
		if self._hook:
			return
		self._stopEvent.clear()
		self._workerThread = threading.Thread(
			target=self._workerLoop,
			name="WorkdayLensMouseScreenshotWorker",
			daemon=True,
		)
		self._workerThread.start()
		self._hookProcRef = HOOKPROC(self._mouseHookProc)
		moduleHandle = kernel32.GetModuleHandleW(None)
		self._hook = user32.SetWindowsHookExW(
			WH_MOUSE_LL,
			self._hookProcRef,
			moduleHandle,
			0,
		)
		if not self._hook:
			self.stop()
			raise ctypes.WinError(ctypes.get_last_error())
		log.info("Workday Lens mouse action logger started.")

	def stop(self):
		try:
			if self._hook:
				user32.UnhookWindowsHookEx(self._hook)
				self._hook = None
				log.info("Workday Lens mouse action logger stopped.")
			self._cancelScrollTimer()
			self._stopEvent.set()
			try:
				self._queue.put_nowait(None)
			except Exception:
				pass
			if self._workerThread:
				self._workerThread.join(timeout=2.0)
				self._workerThread = None
			self._shutdownGdiplus()
		except Exception:
			log.exception("Workday Lens mouse action logger failed to stop cleanly.")

	def _mouseHookProc(self, nCode, wParam, lParam):
		try:
			if nCode == HC_ACTION:
				msg = int(wParam)
				if msg in MOUSE_ACTION_MESSAGES:
					info = ctypes.cast(
						lParam,
						ctypes.POINTER(MSLLHOOKSTRUCT),
					).contents
					self._handleMouseMessage(msg, info)
		except Exception:
			try:
				log.exception("Workday Lens mouse hook callback error.")
			except Exception:
				pass
		return user32.CallNextHookEx(
			self._hook,
			nCode,
			wParam,
			lParam,
		)

	def _handleMouseMessage(self, msg, info):
		eventTime = _utc_now()
		localTime = datetime.now().astimezone()
		record = self._eventRecord(msg, info, eventTime, localTime)
		if record is None:
			return

		captureTask = None
		if self._isScreenshotEnabled():
			if msg in WHEEL_MESSAGES:
				self._scheduleScrollStopCapture(record)
			else:
				captureTask = self._prepareCaptureTask(msg, record, localTime)
		else:
			record["screenshotStatus"] = "disabled"

		if captureTask is not None:
			try:
				self._queue.put_nowait(captureTask)
				record["screenshotStatus"] = "queued"
				captureTask["screenshotStatus"] = "queued"
			except queue.Full:
				record.pop("screenshotPath", None)
				record.pop("screenshotPhase", None)
				record.pop("screenshotDelayMs", None)
				record["screenshotStatus"] = "droppedQueueFull"

		self._sendEvent(
			"mouse_action",
			self._formatMouseActionMessage(record),
			record["eventTimestampUtc"],
		)

	def _eventRecord(self, msg, info, eventTime, localTime):
		eventId = self._nextEventId(localTime)
		record = {
			"eventId": eventId,
			"eventTimestampUtc": _utc_iso(eventTime),
			"action": "",
			"x": int(info.pt.x),
			"y": int(info.pt.y),
			"windowsMessageTimeMs": int(info.time),
			"injected": bool(info.flags & LLMHF_INJECTED),
			"lowerIntegrityInjected": bool(info.flags & LLMHF_LOWER_IL_INJECTED),
		}

		if msg in BUTTON_MESSAGES:
			button, state, action = BUTTON_MESSAGES[msg]
			record.update(
				{
					"action": action,
					"button": button,
					"state": state,
				}
			)
			return record

		if msg in WHEEL_MESSAGES:
			delta = _signed_hiword(int(info.mouseData))
			if msg == WM_MOUSEWHEEL:
				direction = "up" if delta > 0 else "down"
				action = "scrollUp" if delta > 0 else "scrollDown"
				axis = "vertical"
			else:
				direction = "right" if delta > 0 else "left"
				action = "scrollRight" if delta > 0 else "scrollLeft"
				axis = "horizontal"
			record.update(
				{
					"action": action,
					"scrollAxis": axis,
					"scrollDirection": direction,
					"wheelDelta": delta,
					"wheelSteps": delta / float(WHEEL_DELTA),
				}
			)
			return record

		return None

	def _nextEventId(self, localTime):
		with self._eventCounterLock:
			self._eventCounter += 1
			counter = self._eventCounter
		return f"{localTime:%Y%m%dT%H%M%S%f}_{counter:06d}"

	def _prepareCaptureTask(self, msg, record, localTime):
		if msg not in CLICK_DOWN_MESSAGES:
			record["screenshotStatus"] = "notCaptured"
			record["screenshotReason"] = "onlyClickDownCaptured"
			return None

		now = time.monotonic()
		if self._isDuplicateClickDown(record, now):
			record["screenshotStatus"] = "duplicateClickDown"
			record["screenshotReason"] = "firstClickDownAlreadyCaptured"
			return None

		phase = "clickDown"
		delayMs = 0
		filePath = self._capturePath(record, localTime, phase)
		record["screenshotPhase"] = phase
		record["screenshotDelayMs"] = delayMs
		record["screenshotFormat"] = "jpeg"
		record["jpegQuality"] = self.jpegQuality
		record["screenshotPath"] = filePath
		self._lastCapturedClickDown = (
			record.get("button"),
			now,
			int(record.get("x")),
			int(record.get("y")),
		)

		task = dict(record)
		return task

	def _scheduleScrollStopCapture(self, record):
		if not self._isScrollScreenshotEnabled():
			record["screenshotStatus"] = "notCaptured"
			record["screenshotReason"] = "scrollCaptureDisabled"
			return

		record["screenshotStatus"] = "scrollStopPending"
		record["screenshotReason"] = "captureAfterScrollingStops"
		record["scrollStopDelayMs"] = self.scrollStopDelayMs
		pendingRecord = dict(record)

		with self._scrollLock:
			if self._scrollTimer is not None:
				self._scrollTimer.cancel()
			self._lastScrollRecord = pendingRecord
			self._scrollTimer = threading.Timer(
				self.scrollStopDelayMs / 1000.0,
				self._emitScrollStopCapture,
			)
			self._scrollTimer.daemon = True
			self._scrollTimer.start()

	def _cancelScrollTimer(self):
		with self._scrollLock:
			timer = self._scrollTimer
			self._scrollTimer = None
			self._lastScrollRecord = None
		if timer is not None:
			timer.cancel()

	def _emitScrollStopCapture(self):
		if self._stopEvent.is_set():
			return
		with self._scrollLock:
			pendingRecord = self._lastScrollRecord
			self._lastScrollRecord = None
			self._scrollTimer = None
		if pendingRecord is None:
			return
		if not self._isScreenshotEnabled() or not self._isScrollScreenshotEnabled():
			return

		localTime = datetime.now().astimezone()
		eventTime = _utc_now()
		record = dict(pendingRecord)
		record["eventId"] = self._nextEventId(localTime)
		record["eventTimestampUtc"] = _utc_iso(eventTime)
		record["action"] = "scrollStop"
		record["lastScrollAction"] = pendingRecord.get("action")
		record["screenshotPhase"] = "scrollStop"
		record["screenshotDelayMs"] = 0
		record["screenshotFormat"] = "jpeg"
		record["jpegQuality"] = self.jpegQuality
		record["screenshotPath"] = self._capturePath(record, localTime, "scrollStop")
		record["scrollStopDelayMs"] = self.scrollStopDelayMs

		task = dict(record)
		try:
			self._queue.put_nowait(task)
			record["screenshotStatus"] = "queued"
			task["screenshotStatus"] = "queued"
		except queue.Full:
			record.pop("screenshotPath", None)
			record["screenshotStatus"] = "droppedQueueFull"

		self._sendEvent(
			"mouse_action",
			self._formatMouseActionMessage(record),
			record["eventTimestampUtc"],
		)

	def _isDuplicateClickDown(self, record, now):
		if self._lastCapturedClickDown is None:
			return False
		lastButton, lastAt, lastX, lastY = self._lastCapturedClickDown
		if record.get("button") != lastButton:
			return False
		elapsedMs = (now - lastAt) * 1000
		if elapsedMs > self.clickDuplicateSuppressMs:
			return False
		x = int(record.get("x"))
		y = int(record.get("y"))
		return (
			abs(x - lastX) <= self.clickDuplicateMaxDistanceX
			and abs(y - lastY) <= self.clickDuplicateMaxDistanceY
		)

	def _capturePath(self, record, localTime, phase):
		hourDir = os.path.join(
			self.captureRoot,
			f"{localTime:%Y}",
			f"{localTime:%m}",
			f"{localTime:%d}",
			f"{localTime:%H}",
		)
		fileName = (
			f"{record['eventId']}_{phase}_{record['action']}_"
			f"x{record['x']}_y{record['y']}.jpg"
		)
		return os.path.join(hourDir, fileName)

	def _formatMouseActionMessage(self, record):
		payload = {
			"action": record.get("action"),
			"x": record.get("x"),
			"y": record.get("y"),
		}
		if record.get("injected"):
			payload["injected"] = True
		return "[mouse action] " + json.dumps(
			payload,
			ensure_ascii=False,
			separators=(",", ":"),
		)

	def _isScreenshotEnabled(self):
		try:
			return bool(self._screenshotsEnabled())
		except Exception:
			log.exception("Could not read Screen Logger setting.")
			return False

	def _isScrollScreenshotEnabled(self):
		try:
			return bool(self._scrollScreenshotsEnabled())
		except Exception:
			log.exception("Could not read Screen Logger scroll setting.")
			return False

	def _workerLoop(self):
		while not self._stopEvent.is_set():
			item = self._queue.get()
			if item is None:
				break
			try:
				self._processCaptureTask(item)
			except Exception:
				log.exception("Workday Lens screenshot task failed.")

	def _processCaptureTask(self, record):
		delayMs = int(record.get("screenshotDelayMs") or 0)
		if delayMs > 0:
			time.sleep(delayMs / 1000.0)

		filePath = record.get("screenshotPath")
		if not filePath:
			return

		metadata = dict(record)
		try:
			capturedAt = _utc_now()
			screenBounds = self._captureFullVirtualScreenJpeg(
				filePath,
				self.jpegQuality,
				int(record.get("x")),
				int(record.get("y")),
			)
			completedAt = _utc_now()
			metadata["screenshotCapturedAtUtc"] = _utc_iso(capturedAt)
			metadata["screenshotCompletedAtUtc"] = _utc_iso(completedAt)
			metadata["captureLatencyMs"] = self._latencyMs(
				record.get("eventTimestampUtc"),
				capturedAt,
			)
			metadata["screenBounds"] = screenBounds
			metadata["screenshotExists"] = True
		except Exception as exc:
			metadata["screenshotExists"] = False
			metadata["captureError"] = str(exc)
			raise
		finally:
			self._writeMetadata(metadata)

	def _latencyMs(self, eventTimestamp, capturedAt):
		if not eventTimestamp:
			return None
		try:
			normalized = str(eventTimestamp).replace("Z", "+00:00")
			eventTime = datetime.fromisoformat(normalized)
			return int((capturedAt - eventTime).total_seconds() * 1000)
		except Exception:
			return None

	def _writeMetadata(self, metadata):
		filePath = metadata.get("screenshotPath")
		if not filePath:
			return
		dayDir = os.path.dirname(os.path.dirname(filePath))
		os.makedirs(dayDir, exist_ok=True)
		indexPath = os.path.join(dayDir, "mouse_actions.jsonl")
		with open(indexPath, "a", encoding="utf-8") as f:
			f.write(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n")

	def _startGdiplus(self):
		if self._gdiplusStarted:
			return
		startupInput = GdiplusStartupInput(
			1,
			None,
			False,
			False,
		)
		status = gdiplus.GdiplusStartup(
			ctypes.byref(self._gdiplusToken),
			ctypes.byref(startupInput),
			None,
		)
		if status != 0:
			raise RuntimeError(f"GdiplusStartup failed with status {status}")
		self._gdiplusStarted = True

	def _shutdownGdiplus(self):
		if self._gdiplusStarted and self._gdiplusToken:
			gdiplus.GdiplusShutdown(self._gdiplusToken)
		self._gdiplusToken = ctypes.c_void_p()
		self._gdiplusStarted = False

	def _captureFullVirtualScreenJpeg(self, filePath, quality, cursorX, cursorY):
		self._startGdiplus()
		os.makedirs(os.path.dirname(filePath), exist_ok=True)

		left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
		top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
		width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
		height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
		if width <= 0 or height <= 0:
			raise RuntimeError(f"Invalid virtual screen size: {width}x{height}")

		screenDc = user32.GetDC(None)
		if not screenDc:
			raise ctypes.WinError(ctypes.get_last_error())

		memDc = None
		bitmap = None
		oldObject = None
		gpBitmap = ctypes.c_void_p()
		try:
			memDc = gdi32.CreateCompatibleDC(screenDc)
			if not memDc:
				raise ctypes.WinError(ctypes.get_last_error())

			bitmap = gdi32.CreateCompatibleBitmap(screenDc, width, height)
			if not bitmap:
				raise ctypes.WinError(ctypes.get_last_error())

			oldObject = gdi32.SelectObject(memDc, bitmap)
			ok = gdi32.BitBlt(
				memDc,
				0,
				0,
				width,
				height,
				screenDc,
				left,
				top,
				SRCCOPY | CAPTUREBLT,
			)
			if not ok:
				raise ctypes.WinError(ctypes.get_last_error())

			cursorInfo = self._drawCursor(memDc, left, top, cursorX, cursorY)

			status = gdiplus.GdipCreateBitmapFromHBITMAP(
				bitmap,
				None,
				ctypes.byref(gpBitmap),
			)
			if status != 0:
				raise RuntimeError(f"GdipCreateBitmapFromHBITMAP failed with status {status}")

			qualityValue = wintypes.ULONG(int(quality))
			encoderParam = EncoderParameter(
				ENCODER_QUALITY_GUID,
				1,
				ENCODER_PARAMETER_VALUE_TYPE_LONG,
				ctypes.cast(ctypes.byref(qualityValue), ctypes.c_void_p),
			)
			encoderParams = EncoderParameters(
				1,
				(EncoderParameter * 1)(encoderParam),
			)

			status = gdiplus.GdipSaveImageToFile(
				gpBitmap,
				filePath,
				ctypes.byref(JPEG_ENCODER_CLSID),
				ctypes.cast(ctypes.byref(encoderParams), ctypes.c_void_p),
			)
			if status != 0:
				raise RuntimeError(f"GdipSaveImageToFile failed with status {status}")

			return {
				"left": int(left),
				"top": int(top),
				"width": int(width),
				"height": int(height),
				"cursor": cursorInfo,
			}
		finally:
			if gpBitmap:
				gdiplus.GdipDisposeImage(gpBitmap)
			if oldObject and memDc:
				gdi32.SelectObject(memDc, oldObject)
			if bitmap:
				gdi32.DeleteObject(bitmap)
			if memDc:
				gdi32.DeleteDC(memDc)
			if screenDc:
				user32.ReleaseDC(None, screenDc)

	def _drawCursor(self, dc, virtualLeft, virtualTop, cursorX, cursorY):
		info = CURSORINFO()
		info.cbSize = ctypes.sizeof(CURSORINFO)
		if not user32.GetCursorInfo(ctypes.byref(info)):
			return {"drawn": False, "reason": "GetCursorInfoFailed"}
		if not info.hCursor or not (int(info.flags) & CURSOR_SHOWING):
			return {"drawn": False, "reason": "cursorHidden"}

		iconInfo = ICONINFO()
		hotspotX = 0
		hotspotY = 0
		hasIconInfo = bool(user32.GetIconInfo(info.hCursor, ctypes.byref(iconInfo)))
		if hasIconInfo:
			hotspotX = int(iconInfo.xHotspot)
			hotspotY = int(iconInfo.yHotspot)

		drawX = int(cursorX) - int(virtualLeft) - hotspotX
		drawY = int(cursorY) - int(virtualTop) - hotspotY
		try:
			drawn = bool(user32.DrawIconEx(
				dc,
				drawX,
				drawY,
				info.hCursor,
				0,
				0,
				0,
				None,
				DI_NORMAL,
			))
			return {
				"drawn": drawn,
				"x": int(cursorX),
				"y": int(cursorY),
				"drawX": drawX,
				"drawY": drawY,
				"hotspotX": hotspotX,
				"hotspotY": hotspotY,
			}
		finally:
			if hasIconInfo:
				if iconInfo.hbmMask:
					gdi32.DeleteObject(iconInfo.hbmMask)
				if iconInfo.hbmColor:
					gdi32.DeleteObject(iconInfo.hbmColor)
