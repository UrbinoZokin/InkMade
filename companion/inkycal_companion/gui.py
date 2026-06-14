"""Tkinter GUI for the InkyCal companion app.

Tkinter ships with CPython, so the packaged executable needs no extra GUI
runtime. The flow walks the user through:

  1. Find the InkyCal (WiFi first, then Bluetooth).
  2. If only reachable over Bluetooth, collect WiFi SSID/password and set it up.
  3. Pick the Google client-secrets file and sign in.
  4. Deliver the token to the Pi.

All network/BLE work runs on a worker thread; the UI thread only renders the
log and reacts to button presses.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import workflow
from .ble_client import BleDevice
from .discovery import PiDevice


class CompanionApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("InkyCal Setup")
        self.root.geometry("620x560")
        self.root.minsize(560, 480)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.device: Optional[PiDevice] = None
        self.bt_devices: list[BleDevice] = []
        self.credentials_path = tk.StringVar()
        self.ssid = tk.StringVar()
        self.psk = tk.StringVar()
        self.pairing_token = tk.StringVar()
        self.busy = False

        self._build()
        self.root.after(100, self._drain_log)

    # ---------------- UI construction ----------------
    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}

        header = ttk.Label(
            self.root, text="InkyCal Calendar Setup",
            font=("TkDefaultFont", 16, "bold"),
        )
        header.pack(anchor="w", **pad)

        ttk.Label(
            self.root,
            text="Connect your InkyCal to Google Calendar. Make sure your "
                 "InkyCal is powered on and this computer's Bluetooth is enabled.",
            wraplength=580, foreground="#444",
        ).pack(anchor="w", padx=12)

        # Step 1: find device
        step1 = ttk.LabelFrame(self.root, text="1. Find your InkyCal")
        step1.pack(fill="x", **pad)
        self.find_btn = ttk.Button(step1, text="Find My InkyCal", command=self.on_find)
        self.find_btn.pack(side="left", padx=8, pady=8)
        self.device_label = ttk.Label(step1, text="Not connected", foreground="#888")
        self.device_label.pack(side="left", padx=8)

        # Step 2: WiFi setup (only relevant if found over Bluetooth)
        self.step2 = ttk.LabelFrame(self.root, text="2. Set up WiFi (Bluetooth)")
        self.step2.pack(fill="x", **pad)
        wifi_row = ttk.Frame(self.step2)
        wifi_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(wifi_row, text="Network (SSID):", width=16).grid(row=0, column=0, sticky="w")
        ttk.Entry(wifi_row, textvariable=self.ssid, width=28).grid(row=0, column=1, sticky="w")
        ttk.Label(wifi_row, text="Password:", width=16).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(wifi_row, textvariable=self.psk, show="•", width=28).grid(row=1, column=1, sticky="w", pady=4)
        self.wifi_btn = ttk.Button(self.step2, text="Send WiFi to InkyCal", command=self.on_send_wifi, state="disabled")
        self.wifi_btn.pack(anchor="w", padx=8, pady=4)

        # Step 3: Google sign in
        step3 = ttk.LabelFrame(self.root, text="3. Sign in with Google")
        step3.pack(fill="x", **pad)
        cred_row = ttk.Frame(step3)
        cred_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(cred_row, text="Client secrets:", width=16).grid(row=0, column=0, sticky="w")
        ttk.Entry(cred_row, textvariable=self.credentials_path, width=34).grid(row=0, column=1, sticky="w")
        ttk.Button(cred_row, text="Browse…", command=self.on_browse).grid(row=0, column=2, padx=6)
        self.auth_btn = ttk.Button(step3, text="Sign in & Send to InkyCal", command=self.on_authorize, state="disabled")
        self.auth_btn.pack(anchor="w", padx=8, pady=4)

        # Log
        log_frame = ttk.LabelFrame(self.root, text="Progress")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=8, wrap="word", state="disabled",
                                font=("TkFixedFont", 9))
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    # ---------------- helpers ----------------
    def log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.find_btn.configure(state=state)

    def _run_bg(self, target, *args) -> None:
        if self.busy:
            return
        self._set_busy(True)

        def runner():
            try:
                target(*args)
            finally:
                self.root.after(0, lambda: self._set_busy(False))

        threading.Thread(target=runner, daemon=True).start()

    def _set_device(self, device: PiDevice) -> None:
        self.device = device
        self.device_label.configure(
            text=f"Connected: {device.host}", foreground="#2a7"
        )
        self.auth_btn.configure(state="normal")

    # ---------------- button handlers ----------------
    def on_find(self) -> None:
        self._run_bg(self._find_worker)

    def _find_worker(self) -> None:
        device = workflow.find_on_wifi(log=self.log)
        if device:
            self.root.after(0, lambda: self._set_device(device))
            return
        # Fall back to Bluetooth.
        bt = workflow.scan_bluetooth(log=self.log)
        self.bt_devices = bt
        if bt:
            self.root.after(0, self._enable_wifi_step)
        else:
            self.root.after(0, lambda: messagebox.showwarning(
                "Not found",
                "No InkyCal found on WiFi or Bluetooth.\n\n"
                "Check that the device is powered on, then try again.",
            ))

    def _enable_wifi_step(self) -> None:
        self.device_label.configure(
            text="Found over Bluetooth — set up WiFi", foreground="#b80"
        )
        self.wifi_btn.configure(state="normal")
        messagebox.showinfo(
            "Bluetooth setup",
            "Your InkyCal isn't on WiFi yet. Enter your WiFi network name and "
            "password in step 2, then click 'Send WiFi to InkyCal'.",
        )

    def on_send_wifi(self) -> None:
        if not self.bt_devices:
            return
        if not self.ssid.get().strip():
            messagebox.showerror("WiFi", "Enter a WiFi network name (SSID).")
            return
        self._run_bg(self._send_wifi_worker)

    def _send_wifi_worker(self) -> None:
        try:
            device = workflow.provision_wifi_over_ble(
                self.bt_devices[0].address,
                self.ssid.get().strip(),
                self.psk.get(),
                log=self.log,
            )
        except Exception as exc:
            self.root.after(0, lambda e=exc: messagebox.showerror("WiFi setup failed", str(e)))
            return
        self.root.after(0, lambda: self._set_device(device))

    def on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Google OAuth client-secrets JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.credentials_path.set(path)

    def on_authorize(self) -> None:
        if not self.device:
            messagebox.showerror("Not connected", "Find your InkyCal first.")
            return
        if not self.credentials_path.get():
            messagebox.showerror("Missing file", "Choose your Google client-secrets JSON.")
            return
        self._run_bg(self._authorize_worker)

    def _authorize_worker(self) -> None:
        try:
            token = workflow.run_google_signin(self.credentials_path.get(), log=self.log)
        except Exception as exc:
            self.root.after(0, lambda e=exc: messagebox.showerror("Google sign-in failed", str(e)))
            return
        try:
            workflow.upload_token(
                self.device, token,
                pairing_token=self.pairing_token.get().strip(),
                log=self.log,
            )
        except Exception as exc:
            self.root.after(0, lambda e=exc: messagebox.showerror("Upload failed", str(e)))
            return
        self.root.after(0, lambda: messagebox.showinfo(
            "Done", "Your calendar is connected! The InkyCal display will refresh shortly.",
        ))


def main() -> int:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    CompanionApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
