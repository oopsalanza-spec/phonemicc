"""
PhoneMic Receiver — GUI version
A real window (like WO Mic's PC app) showing your PC's IP address and live
connection status, instead of a command-line console.
"""

import socket
import struct
import threading
import time
import queue
import tkinter as tk
from tkinter import ttk

import numpy as np
import sounddevice as sd

LISTEN_PORT = 50505
CABLE_NAME_HINT = "CABLE Input"


def find_cable_device():
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if CABLE_NAME_HINT.lower() in dev["name"].lower() and dev["max_output_channels"] > 0:
            return idx
    return None


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class ReceiverEngine:
    """Runs the socket server + audio streaming in a background thread and
    reports status back to the GUI via a thread-safe queue."""

    def __init__(self, status_queue: queue.Queue):
        self.status_queue = status_queue
        self.running = True

    def log(self, msg):
        self.status_queue.put(msg)

    def run(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", LISTEN_PORT))
        server.listen(1)
        server.settimeout(1.0)

        local_ip = socket.gethostbyname(socket.gethostname())
        self.log(f"READY|{local_ip}:{LISTEN_PORT}")

        while self.running:
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.handle_client(conn, addr)

    def handle_client(self, conn, addr):
        self.log(f"CONNECTED|{addr[0]}")
        header = recv_exact(conn, 8)
        if not header:
            self.log("STATUS|Connection closed before handshake")
            return

        sample_rate, channels = struct.unpack("<II", header)
        channels = max(1, channels)
        self.log(f"STATUS|Streaming: {sample_rate} Hz, {channels} ch")

        device_idx = find_cable_device()
        if device_idx is None:
            self.log("ERROR|VB-Cable not found. Reinstall PhoneMic.")
            conn.close()
            return

        frame_bytes = 2 * channels

        def callback(outdata, frames, time_info, status):
            data = recv_exact(conn, frames * frame_bytes)
            if data is None:
                raise sd.CallbackStop()
            samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
            outdata[:] = samples.reshape(-1, channels)

        try:
            with sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                device=device_idx,
                callback=callback,
                blocksize=1024,
            ):
                while self.running:
                    time.sleep(0.3)
        except Exception as e:
            self.log(f"STATUS|Stream ended: {e}")
        finally:
            conn.close()
            self.log("DISCONNECTED|")


class App:
    def __init__(self, root):
        self.root = root
        root.title("PhoneMic Receiver")
        root.geometry("380x260")
        root.resizable(False, False)

        pad = {"padx": 16, "pady": 8}

        self.status_dot = tk.Canvas(root, width=16, height=16, highlightthickness=0)
        self.dot = self.status_dot.create_oval(2, 2, 14, 14, fill="#c0392b")
        self.status_dot.grid(row=0, column=0, **pad)

        self.state_label = ttk.Label(root, text="Waiting for phone...", font=("Segoe UI", 11, "bold"))
        self.state_label.grid(row=0, column=1, sticky="w", **pad)

        ttk.Separator(root, orient="horizontal").grid(row=1, column=0, columnspan=2, sticky="ew", padx=16)

        ttk.Label(root, text="Enter this IP address in the PhoneMic iPhone app:",
                  font=("Segoe UI", 9)).grid(row=2, column=0, columnspan=2, sticky="w", **pad)

        self.ip_label = ttk.Label(root, text="Starting...", font=("Consolas", 16, "bold"), foreground="#2980b9")
        self.ip_label.grid(row=3, column=0, columnspan=2, **pad)

        self.detail_label = ttk.Label(root, text="", font=("Segoe UI", 9), foreground="#555")
        self.detail_label.grid(row=4, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(root, text="Mic output device: CABLE Output (VB-Audio Virtual Cable)\n"
                              "Pick that as the microphone in Discord/Zoom/OBS/etc.",
                  font=("Segoe UI", 8), foreground="#777", justify="left").grid(
            row=5, column=0, columnspan=2, sticky="w", padx=16, pady=(20, 8))

        self.status_queue = queue.Queue()
        self.engine = ReceiverEngine(self.status_queue)
        threading.Thread(target=self.engine.run, daemon=True).start()

        self.root.after(100, self.poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def poll_queue(self):
        try:
            while True:
                msg = self.status_queue.get_nowait()
                self.handle_message(msg)
        except queue.Empty:
            pass
        self.root.after(150, self.poll_queue)

    def handle_message(self, msg):
        kind, _, value = msg.partition("|")
        if kind == "READY":
            self.ip_label.config(text=value)
            self.detail_label.config(text="Waiting for phone to connect...")
        elif kind == "CONNECTED":
            self.state_label.config(text="Phone connected")
            self.status_dot.itemconfig(self.dot, fill="#27ae60")
            self.detail_label.config(text=f"From {value}")
        elif kind == "STATUS":
            self.detail_label.config(text=value)
        elif kind == "DISCONNECTED":
            self.state_label.config(text="Waiting for phone...")
            self.status_dot.itemconfig(self.dot, fill="#c0392b")
            self.detail_label.config(text="Phone disconnected")
        elif kind == "ERROR":
            self.state_label.config(text="Error")
            self.status_dot.itemconfig(self.dot, fill="#c0392b")
            self.detail_label.config(text=value)

    def on_close(self):
        self.engine.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
