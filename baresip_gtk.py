#!/usr/bin/env python3
import json
import socket
import threading
import subprocess
import time
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

HOST = "127.0.0.1"
PORT = 4444


class BaresipGUI(Gtk.Window):
    def __init__(self):
        super().__init__(title="Baresip Softphone")
        self.set_default_size(280, 420)
        self.set_border_width(12)
        self.set_resizable(False)
        self.sock = None
        self.running = True

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Status-Anzeige
        self.status_label = Gtk.Label(label="Verbinde mit baresip...")
        self.status_label.set_line_wrap(True)
        vbox.pack_start(self.status_label, False, False, 4)

        # Eingabefeld für Nummer / SIP-URI
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Rufnummer oder SIP-URI...")
        self.entry.connect("activate", self.on_dial)
        vbox.pack_start(self.entry, False, False, 0)

        # Ziffernblock
        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(True)
        buttons = [
            ("1", 0, 0), ("2", 1, 0), ("3", 2, 0),
            ("4", 0, 1), ("5", 1, 1), ("6", 2, 1),
            ("7", 0, 2), ("8", 1, 2), ("9", 2, 2),
            ("*", 0, 3), ("0", 1, 3), ("#", 2, 3),
        ]
        for label, col, row in buttons:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self.on_digit, label)
            grid.attach(btn, col, row, 1, 1)
        vbox.pack_start(grid, True, True, 0)

        # Löschen-Button
        clear_btn = Gtk.Button(label="⌫ Löschen")
        clear_btn.connect("clicked", self.on_backspace)
        vbox.pack_start(clear_btn, False, False, 0)

        # Anruf-Steuerung (Anrufen / Annehmen / Auflegen)
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_box.set_homogeneous(True)

        dial_btn = Gtk.Button(label="📞 Wählen")
        dial_btn.connect("clicked", self.on_dial)
        action_box.pack_start(dial_btn, True, True, 0)

        accept_btn = Gtk.Button(label="✅ Annehmen")
        accept_btn.connect("clicked", lambda _: self.send_cmd("accept"))
        action_box.pack_start(accept_btn, True, True, 0)

        hangup_btn = Gtk.Button(label="❌ Auflegen")
        hangup_btn.connect("clicked", lambda _: self.send_cmd("hangup"))
        action_box.pack_start(hangup_btn, True, True, 0)

        vbox.pack_start(action_box, False, False, 4)

        self.connect("destroy", self.on_quit)
        threading.Thread(target=self.connect_loop, daemon=True).start()

    def on_digit(self, _widget, digit):
        pos = self.entry.get_position()
        self.entry.insert_text(digit, pos)
        self.entry.set_position(pos + 1)
        # Sendet DTMF-Ton, falls gerade ein Gespräch läuft
        self.send_cmd("sndcode", digit)

    def on_backspace(self, _widget):
        text = self.entry.get_text()
        if text:
            self.entry.set_text(text[:-1])
            self.entry.set_position(len(text) - 1)

    def on_dial(self, _widget):
        target = self.entry.get_text().strip()
        if target:
            self.send_cmd("dial", target)
            self.set_status(f"Rufe an: {target}")

    def send_cmd(self, command, params=""):
        if not self.sock:
            return
        payload = json.dumps({"command": command, "params": params})
        # Baresip ctrl_tcp nutzt Netstring-Format: <länge>:<json>,
        netstring = f"{len(payload)}:{payload},".encode("utf-8")
        try:
            self.sock.sendall(netstring)
        except OSError:
            self.set_status("Verbindung verloren...")

    def set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def connect_loop(self):
        while self.running:
            try:
                s = socket.create_connection((HOST, PORT), timeout=3)
                s.settimeout(None)
                self.sock = s
                self.set_status("Bereit (mit baresip verbunden)")
                self.read_events(s)
            except OSError:
                self.sock = None
                self.set_status("Warte auf baresip (127.0.0.1:4444)...")
                time.sleep(2)

    def read_events(self, sock):
        buf = b""
        while self.running:
            data = sock.recv(4096)
            if not data:
                break
            buf += data
            # Netstrings parsen
            while b":" in buf:
                length_str, rest = buf.split(b":", 1)
                if not length_str.isdigit():
                    buf = b""
                    break
                length = int(length_str)
                if len(rest) < length + 1:
                    break
                msg = rest[:length].decode("utf-8", errors="ignore")
                buf = rest[length + 1 :]
                self.handle_event(msg)

    def handle_event(self, raw_json):
        try:
            ev = json.loads(raw_json)
        except json.JSONDecodeError:
            return
        etype = ev.get("type", "")
        peer = ev.get("peeruri", "")
        if etype == "CALL_INCOMING":
            self.set_status(f"Eingehender Anruf:\n{peer}")
            GLib.idle_add(self.present)
        elif etype == "CALL_ESTABLISHED":
            self.set_status(f"Verbunden mit:\n{peer}")
        elif etype == "CALL_CLOSED":
            self.set_status("Anruf beendet – Bereit")
        elif etype == "REGISTER_OK":
            self.set_status("SIP-Account registriert")
        elif etype == "REGISTER_FAIL":
            self.set_status("Registrierung fehlgeschlagen!")

    def on_quit(self, _widget):
        self.running = False
        if self.sock:
            self.sock.close()
        Gtk.main_quit()


if __name__ == "__main__":
    # Startet baresip als Daemon im Hintergrund, falls es noch nicht läuft
    subprocess.Popen(["baresip", "-d"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    win = BaresipGUI()
    win.show_all()
    Gtk.main()
