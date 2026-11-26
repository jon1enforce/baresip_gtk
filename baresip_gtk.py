#!/usr/bin/env python3
import os
import re
import json
import time
import socket
import threading
import subprocess
from datetime import datetime

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

HOST = "127.0.0.1"
PORT = 4444
BARESIP_DIR = os.path.expanduser("~/.baresip")
ACCOUNTS_FILE = os.path.join(BARESIP_DIR, "accounts")
CONTACTS_FILE = os.path.join(BARESIP_DIR, "contacts")

CSS_STYLE = b"""
* {
    font-family: "Roboto", Sans;
    font-size: 18px;
}
window, notebook, notebook > stack, box, grid, scrolledwindow, viewport {
    background-color: #08120e;
    color: #ffffff;
}
notebook > header {
    background-color: #050c09;
    border-bottom: 2px solid #1e523a;
    padding: 6px;
}
notebook > header > tabs > tab {
    background-color: #0e241b;
    color: #c5ded2;
    min-height: 62px;
    min-width: 118px;
    padding: 12px 14px;
    margin: 4px;
    border: 2px solid #1c4a35;
    border-radius: 10px;
    font-weight: bold;
    font-size: 17px;
}
notebook > header > tabs > tab:checked {
    background-color: #1b6944;
    color: #ffffff;
    border: 2px solid #38b87c;
}

entry, textview, textview text {
    background-color: #0e1f18;
    color: #ffffff;
    border: 2px solid #266347;
    border-radius: 10px;
    min-height: 56px;
    padding: 10px 14px;
    font-size: 20px;
    caret-color: #4ade80;
}
button {
    background-image: none;
    background-color: #133b29;
    color: #ffffff;
    border: 2px solid #276e4e;
    border-radius: 12px;
    min-height: 64px;
    padding: 12px 16px;
    font-weight: bold;
    font-size: 19px;
}
button:hover {
    background-color: #1a5239;
    border-color: #38a172;
}
button:active, button:checked {
    background-color: #23734f;
    color: #ffffff;
    border-color: #52e09e;
}
button.dialpad-btn {
    font-size: 30px;
    min-height: 86px;
    background-color: #0f2e20;
}
button.call-btn {
    background-color: #167a47;
    border-color: #2ecc71;
    min-height: 74px;
    font-size: 21px;
}
button.call-btn:hover {
    background-color: #1d9658;
}
button.hangup-btn {
    background-color: #871f1f;
    border-color: #d94141;
    min-height: 74px;
    font-size: 21px;
}
button.hangup-btn:hover {
    background-color: #a82828;
}
button.warn-btn:checked {
    background-color: #9e6711;
    border-color: #f5a623;
}
treeview {
    background-color: #0c1a14;
    color: #ffffff;
    font-size: 19px;
}
treeview:selected {
    background-color: #1e6b46;
    color: #ffffff;
}
treeview header button {
    background-color: #08140f;
    color: #a7d1bd;
    border: 1px solid #1e523a;
    min-height: 48px;
}
frame > border {
    border: 2px solid #1f543c;
    border-radius: 12px;
}
frame > label {
    color: #6ee7b7;
    font-weight: bold;
    font-size: 18px;
    padding: 0 8px;
}
#status-banner {
    background-color: #113324;
    border: 2px solid #2b7a56;
    border-radius: 12px;
    padding: 16px;
    color: #ffffff;
    font-weight: bold;
    font-size: 21px;
}
"""
class BaresipTouchApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Baresip Touch Softphone")
        self.set_default_size(1080, 1920)
        self.set_border_width(14)

        self.apply_css()

        self.sock = None
        self.running = True
        self.is_muted = False
        self.is_held = False
        self.is_dnd = False
        self.active_calls = {}

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(root)

        self.status_label = Gtk.Label(label="Verbinde mit baresip...")
        self.status_label.set_name("status-banner")
        self.status_label.set_line_wrap(True)
        root.pack_start(self.status_label, False, False, 0)

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        root.pack_start(self.notebook, True, True, 0)

        self.notebook.append_page(self.build_phone_tab(), Gtk.Label(label="Telefon"))
        self.notebook.append_page(self.build_lines_tab(), Gtk.Label(label="Leitungen"))
        self.notebook.append_page(self.build_contacts_tab(), Gtk.Label(label="Kontakte"))
        self.notebook.append_page(self.build_history_tab(), Gtk.Label(label="Verlauf"))
        self.notebook.append_page(self.build_chat_tab(), Gtk.Label(label="Chat"))
        self.notebook.append_page(self.build_accounts_tab(), Gtk.Label(label="Accounts"))
        self.notebook.append_page(self.build_av_tab(), Gtk.Label(label="Audio/Video"))
        self.notebook.append_page(self.build_debug_tab(), Gtk.Label(label="Debug"))

        self.connect("destroy", self.on_quit)
        self.load_contacts_from_file()
        self.load_accounts_from_file()

        threading.Thread(target=self.connect_loop, daemon=True).start()

    def apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS_STYLE)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
    def build_phone_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_border_width(12)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Rufnummer oder sip:user@domain...")
        self.entry.connect("activate", lambda _: self.on_dial(video=False))
        top_row.pack_start(self.entry, True, True, 0)

        del_btn = Gtk.Button(label="⌫")
        del_btn.set_size_request(84, -1)
        del_btn.connect("clicked", self.on_backspace)
        top_row.pack_start(del_btn, False, False, 0)

        clr_btn = Gtk.Button(label="C")
        clr_btn.set_size_request(84, -1)
        clr_btn.connect("clicked", lambda _: self.entry.set_text(""))
        top_row.pack_start(clr_btn, False, False, 0)

        box.pack_start(top_row, False, False, 0)

        pad = Gtk.Grid(row_spacing=12, column_spacing=12)
        pad.set_row_homogeneous(True)
        pad.set_column_homogeneous(True)
        keys = [
            ("1", 0, 0), ("2", 1, 0), ("3", 2, 0),
            ("4", 0, 1), ("5", 1, 1), ("6", 2, 1),
            ("7", 0, 2), ("8", 1, 2), ("9", 2, 2),
            ("*", 0, 3), ("0", 1, 3), ("#", 2, 3),
        ]
        for lbl, c, r in keys:
            b = Gtk.Button(label=lbl)
            b.get_style_context().add_class("dialpad-btn")
            b.connect("clicked", self.on_digit, lbl)
            pad.attach(b, c, r, 1, 1)
        box.pack_start(pad, True, True, 0)

        call_grid = Gtk.Grid(row_spacing=10, column_spacing=10)
        call_grid.set_column_homogeneous(True)

        dial_btn = Gtk.Button(label="Audio-Anruf")
        dial_btn.get_style_context().add_class("call-btn")
        dial_btn.connect("clicked", lambda _: self.on_dial(video=False))
        call_grid.attach(dial_btn, 0, 0, 1, 1)

        vid_dial_btn = Gtk.Button(label="Video-Anruf")
        vid_dial_btn.get_style_context().add_class("call-btn")
        vid_dial_btn.connect("clicked", lambda _: self.on_dial(video=True))
        call_grid.attach(vid_dial_btn, 1, 0, 1, 1)

        ans_btn = Gtk.Button(label="Annehmen")
        ans_btn.get_style_context().add_class("call-btn")
        ans_btn.connect("clicked", lambda _: self.send_cmd("accept"))
        call_grid.attach(ans_btn, 0, 1, 1, 1)

        end_btn = Gtk.Button(label="Auflegen")
        end_btn.get_style_context().add_class("hangup-btn")
        end_btn.connect("clicked", lambda _: self.send_cmd("hangup"))
        call_grid.attach(end_btn, 1, 1, 1, 1)

        box.pack_start(call_grid, False, False, 0)

        ctrl_frame = Gtk.Frame(label=" Gesprächssteuerung ")
        cgrid = Gtk.Grid(row_spacing=10, column_spacing=10)
        cgrid.set_border_width(12)
        cgrid.set_column_homogeneous(True)

        self.mute_btn = Gtk.ToggleButton(label="Mute (Stumm)")
        self.mute_btn.get_style_context().add_class("warn-btn")
        self.mute_btn.connect("toggled", self.on_toggle_mute)
        cgrid.attach(self.mute_btn, 0, 0, 1, 1)

        self.hold_btn = Gtk.ToggleButton(label="Halten / Resume")
        self.hold_btn.get_style_context().add_class("warn-btn")
        self.hold_btn.connect("toggled", self.on_toggle_hold)
        cgrid.attach(self.hold_btn, 1, 0, 1, 1)

        xfer_btn = Gtk.Button(label="Weiterleiten")
        xfer_btn.connect("clicked", self.on_transfer_dialog)
        cgrid.attach(xfer_btn, 0, 1, 1, 1)

        self.dnd_btn = Gtk.ToggleButton(label="Nicht stören (DND)")
        self.dnd_btn.get_style_context().add_class("warn-btn")
        self.dnd_btn.connect("toggled", self.on_toggle_dnd)
        cgrid.attach(self.dnd_btn, 1, 1, 1, 1)

        ctrl_frame.add(cgrid)
        box.pack_start(ctrl_frame, False, False, 0)
        return box
    def build_lines_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(12)

        lbl = Gtk.Label(label="Parallele Anrufe (Antippen & Aktivieren oder Konferenz):")
        lbl.set_xalign(0)
        box.pack_start(lbl, False, False, 0)

        self.calls_store = Gtk.ListStore(str, str, str, str)
        self.calls_tree = Gtk.TreeView(model=self.calls_store)
        for i, title in enumerate(["ID", "Teilnehmer", "Status", "Richtung"]):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            self.calls_tree.append_column(col)
        self.calls_tree.connect("row-activated", self.on_switch_call_row)

        sc = Gtk.ScrolledWindow()
        sc.add(self.calls_tree)
        box.pack_start(sc, True, True, 0)

        grid = Gtk.Grid(row_spacing=10, column_spacing=10)
        grid.set_column_homogeneous(True)

        b_ref = Gtk.Button(label="Aktualisieren")
        b_ref.connect("clicked", lambda _: self.send_cmd("listcalls"))
        grid.attach(b_ref, 0, 0, 1, 1)

        b_act = Gtk.Button(label="Leitung wechseln")
        b_act.connect("clicked", self.on_activate_selected_call)
        grid.attach(b_act, 1, 0, 1, 1)

        b_conf = Gtk.Button(label="Konferenz (Alle)")
        b_conf.get_style_context().add_class("call-btn")
        b_conf.connect("clicked", self.on_start_conference)
        grid.attach(b_conf, 0, 1, 1, 1)

        b_all = Gtk.Button(label="Alle auflegen")
        b_all.get_style_context().add_class("hangup-btn")
        b_all.connect("clicked", lambda _: self.send_cmd("hangupall"))
        grid.attach(b_all, 1, 1, 1, 1)

        box.pack_start(grid, False, False, 0)
        return box

    def build_contacts_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(12)

        self.contact_name = Gtk.Entry()
        self.contact_name.set_placeholder_text("Kontaktname...")
        box.pack_start(self.contact_name, False, False, 0)

        row_in = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.contact_uri = Gtk.Entry()
        self.contact_uri.set_placeholder_text("sip:benutzer@server")
        row_in.pack_start(self.contact_uri, True, True, 0)

        add_b = Gtk.Button(label="Speichern")
        add_b.connect("clicked", self.on_add_contact)
        row_in.pack_start(add_b, False, False, 0)
        box.pack_start(row_in, False, False, 0)

        self.contacts_store = Gtk.ListStore(str, str)
        self.contacts_tree = Gtk.TreeView(model=self.contacts_store)
        for i, title in enumerate(["Name", "SIP-Adresse"]):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            self.contacts_tree.append_column(col)
        self.contacts_tree.connect("row-activated", self.on_call_contact_row)

        sc = Gtk.ScrolledWindow()
        sc.add(self.contacts_tree)
        box.pack_start(sc, True, True, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btns.set_homogeneous(True)

        c_call = Gtk.Button(label="Anrufen")
        c_call.get_style_context().add_class("call-btn")
        c_call.connect("clicked", self.on_call_selected_contact)
        btns.pack_start(c_call, True, True, 0)

        c_del = Gtk.Button(label="Löschen")
        c_del.get_style_context().add_class("hangup-btn")
        c_del.connect("clicked", self.on_delete_contact)
        btns.pack_start(c_del, True, True, 0)

        box.pack_start(btns, False, False, 0)
        return box

    def build_history_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(12)

        self.history_store = Gtk.ListStore(str, str, str)
        self.history_tree = Gtk.TreeView(model=self.history_store)
        for i, title in enumerate(["Uhrzeit", "Typ", "Teilnehmer"]):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            self.history_tree.append_column(col)
        self.history_tree.connect("row-activated", self.on_redial_row)

        sc = Gtk.ScrolledWindow()
        sc.add(self.history_tree)
        box.pack_start(sc, True, True, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btns.set_homogeneous(True)

        b_re = Gtk.Button(label="Rückruf starten")
        b_re.get_style_context().add_class("call-btn")
        b_re.connect("clicked", self.on_redial_selected)
        btns.pack_start(b_re, True, True, 0)

        b_cl = Gtk.Button(label="Verlauf leeren")
        b_cl.connect("clicked", lambda _: self.history_store.clear())
        btns.pack_start(b_cl, True, True, 0)

        box.pack_start(btns, False, False, 0)
        return box
    def build_chat_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(12)

        self.msg_peer = Gtk.Entry()
        self.msg_peer.set_placeholder_text("Empfänger (sip:user@domain)...")
        box.pack_start(self.msg_peer, False, False, 0)

        self.msg_view = Gtk.TextView()
        self.msg_view.set_editable(False)
        self.msg_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.msg_buf = self.msg_view.get_buffer()

        sc = Gtk.ScrolledWindow()
        sc.add(self.msg_view)
        box.pack_start(sc, True, True, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.msg_input = Gtk.Entry()
        self.msg_input.set_placeholder_text("Textnachricht schreiben...")
        self.msg_input.connect("activate", self.on_send_message)
        row.pack_start(self.msg_input, True, True, 0)

        s_btn = Gtk.Button(label="Senden")
        s_btn.get_style_context().add_class("call-btn")
        s_btn.connect("clicked", self.on_send_message)
        row.pack_start(s_btn, False, False, 0)

        box.pack_start(row, False, False, 0)
        return box

    def build_accounts_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(12)

        form = Gtk.Frame(label=" Neuen SIP-Account anlegen ")
        fg = Gtk.Grid(row_spacing=10, column_spacing=10)
        fg.set_border_width(12)

        self.acc_user = Gtk.Entry()
        self.acc_user.set_placeholder_text("Benutzername (z.B. 620)")
        self.acc_server = Gtk.Entry()
        self.acc_server.set_placeholder_text("Registrar / Server (z.B. fritz.box)")
        self.acc_pass = Gtk.Entry()
        self.acc_pass.set_placeholder_text("Passwort")
        self.acc_pass.set_visibility(False)

        fg.attach(Gtk.Label(label="User:"), 0, 0, 1, 1)
        fg.attach(self.acc_user, 1, 0, 1, 1)
        fg.attach(Gtk.Label(label="Server:"), 0, 1, 1, 1)
        fg.attach(self.acc_server, 1, 1, 1, 1)
        fg.attach(Gtk.Label(label="Passwort:"), 0, 2, 1, 1)
        fg.attach(self.acc_pass, 1, 2, 1, 1)

        save_btn = Gtk.Button(label="Speichern & Registrieren")
        save_btn.get_style_context().add_class("call-btn")
        save_btn.connect("clicked", self.on_save_account)
        fg.attach(save_btn, 0, 3, 2, 1)

        form.add(fg)
        box.pack_start(form, False, False, 0)

        self.acc_store = Gtk.ListStore(str)
        self.acc_tree = Gtk.TreeView(model=self.acc_store)
        col = Gtk.TreeViewColumn("Aktive Accounts (~/.baresip/accounts)", Gtk.CellRendererText(), text=0)
        self.acc_tree.append_column(col)

        sc = Gtk.ScrolledWindow()
        sc.add(self.acc_tree)
        box.pack_start(sc, True, True, 0)

        grid = Gtk.Grid(row_spacing=10, column_spacing=10)
        grid.set_column_homogeneous(True)

        b_reg = Gtk.Button(label="Registrierung prüfen")
        b_reg.connect("clicked", lambda _: self.send_cmd("reginfo"))
        grid.attach(b_reg, 0, 0, 1, 1)

        b_next = Gtk.Button(label="Leitung wechseln")
        b_next.connect("clicked", lambda _: self.send_cmd("uanext"))
        grid.attach(b_next, 1, 0, 1, 1)

        b_rereg = Gtk.Button(label="Neu registrieren")
        b_rereg.connect("clicked", lambda _: self.send_cmd("uareg", "0"))
        grid.attach(b_rereg, 0, 1, 1, 1)

        b_del = Gtk.Button(label="Account löschen")
        b_del.get_style_context().add_class("hangup-btn")
        b_del.connect("clicked", self.on_delete_account)
        grid.attach(b_del, 1, 1, 1, 1)

        box.pack_start(grid, False, False, 0)
        return box
    def build_av_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_border_width(12)

        a_frame = Gtk.Frame(label=" Audio-Geräte (ALSA / Pulse / PipeWire) ")
        ag = Gtk.Grid(row_spacing=10, column_spacing=10)
        ag.set_border_width(12)

        self.ausrc_entry = Gtk.Entry()
        self.ausrc_entry.set_placeholder_text("z.B. alsa,default oder pulse")
        b_mic = Gtk.Button(label="Mikrofon setzen")
        b_mic.connect("clicked", lambda _: self.send_cmd("ausrc", self.ausrc_entry.get_text().strip()))

        self.auplay_entry = Gtk.Entry()
        self.auplay_entry.set_placeholder_text("z.B. alsa,default oder pulse")
        b_spk = Gtk.Button(label="Ausgang setzen")
        b_spk.connect("clicked", lambda _: self.send_cmd("auplay", self.auplay_entry.get_text().strip()))

        ag.attach(Gtk.Label(label="Mikrofon:"), 0, 0, 1, 1)
        ag.attach(self.ausrc_entry, 1, 0, 1, 1)
        ag.attach(b_mic, 0, 1, 2, 1)

        ag.attach(Gtk.Label(label="Lautsprecher:"), 0, 2, 1, 1)
        ag.attach(self.auplay_entry, 1, 2, 1, 1)
        ag.attach(b_spk, 0, 3, 2, 1)
        a_frame.add(ag)
        box.pack_start(a_frame, False, False, 0)

        v_frame = Gtk.Frame(label=" Video- & Kamera-Steuerung ")
        vg = Gtk.Grid(row_spacing=10, column_spacing=10)
        vg.set_border_width(12)
        vg.set_column_homogeneous(True)

        self.vidsrc_entry = Gtk.Entry()
        self.vidsrc_entry.set_placeholder_text("z.B. v4l2,/dev/video0")
        vg.attach(self.vidsrc_entry, 0, 0, 2, 1)

        b_vsrc = Gtk.Button(label="Kamera setzen")
        b_vsrc.connect("clicked", lambda _: self.send_cmd("vidsrc", self.vidsrc_entry.get_text().strip()))
        vg.attach(b_vsrc, 0, 1, 1, 1)

        b_self = Gtk.Button(label="Selbstansicht (Selfview)")
        b_self.connect("clicked", lambda _: self.send_cmd("selfview"))
        vg.attach(b_self, 1, 1, 1, 1)

        b_snap = Gtk.Button(label="Video-Schnappschuss")
        b_snap.connect("clicked", lambda _: self.send_cmd("snapshot"))
        vg.attach(b_snap, 0, 2, 1, 1)

        b_vdir = Gtk.Button(label="Video senden/stoppen")
        b_vdir.connect("clicked", lambda _: self.send_cmd("vidtoggle"))
        vg.attach(b_vdir, 1, 2, 1, 1)

        v_frame.add(vg)
        box.pack_start(v_frame, False, False, 0)
        return box

    def build_debug_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(12)

        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        grid.set_column_homogeneous(True)

        cmds = [
            ("Call-Stats", "callstat"),
            ("SIP-Status", "sipstat"),
            ("System-Info", "sysinfo"),
            ("Netzwerk-Info", "netstat"),
            ("Geladene Module", "modules"),
            ("Config Reload", "conf_reload"),
        ]
        for idx, (label, cmd) in enumerate(cmds):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _, c=cmd: self.send_cmd(c))
            grid.attach(b, idx % 2, idx // 2, 1, 1)
        box.pack_start(grid, False, False, 0)

        cmd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.raw_cmd_entry = Gtk.Entry()
        self.raw_cmd_entry.set_placeholder_text("Freier baresip-Befehl (z.B. /help)...")
        self.raw_cmd_entry.connect("activate", self.on_send_raw_cmd)
        cmd_row.pack_start(self.raw_cmd_entry, True, True, 0)

        run_btn = Gtk.Button(label="Ausführen")
        run_btn.connect("clicked", self.on_send_raw_cmd)
        cmd_row.pack_start(run_btn, False, False, 0)
        box.pack_start(cmd_row, False, False, 0)

        self.sys_view = Gtk.TextView()
        self.sys_view.set_editable(False)
        self.sys_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.sys_buf = self.sys_view.get_buffer()

        sc = Gtk.ScrolledWindow()
        sc.add(self.sys_view)
        box.pack_start(sc, True, True, 0)

        clr_log = Gtk.Button(label="Debug-Log leeren")
        clr_log.connect("clicked", lambda _: self.sys_buf.set_text(""))
        box.pack_start(clr_log, False, False, 0)
        return box
    def on_digit(self, _w, digit):
        pos = self.entry.get_position()
        self.entry.insert_text(digit, pos)
        self.entry.set_position(pos + 1)
        self.send_cmd("sndcode", digit)

    def on_backspace(self, _w):
        txt = self.entry.get_text()
        if txt:
            self.entry.set_text(txt[:-1])
            self.entry.set_position(len(txt) - 1)

    def on_dial(self, video=False):
        target = self.entry.get_text().strip()
        if not target:
            return
        if video:
            self.send_cmd("dialdir", f"{target} sendrecv sendrecv")
            self.add_history("Video-Out", target)
            self.set_status(f"Video-Anruf: {target}")
        else:
            self.send_cmd("dial", target)
            self.add_history("Ausgehend", target)
            self.set_status(f"Rufe an: {target}")

    def on_toggle_mute(self, btn):
        self.is_muted = btn.get_active()
        self.send_cmd("mute")
        self.set_status("Mikrofon STUMM" if self.is_muted else "Mikrofon AKTIV")

    def on_toggle_hold(self, btn):
        self.is_held = btn.get_active()
        if self.is_held:
            self.send_cmd("hold")
            self.set_status("Gespräch auf HALTEN")
        else:
            self.send_cmd("resume")
            self.set_status("Gespräch FORTGESETZT")

    def on_toggle_dnd(self, btn):
        self.is_dnd = btn.get_active()
        self.send_cmd("dnd", "yes" if self.is_dnd else "no")
        self.set_status("Nicht stören (DND) AN" if self.is_dnd else "Bereit")

    def on_transfer_dialog(self, _w):
        dlg = Gtk.Dialog(title="Anruf weiterleiten", transient_for=self, flags=0)
        dlg.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL, "Weiterleiten", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_border_width(14)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Zielnummer oder sip:user@domain")
        box.add(entry)
        dlg.show_all()
        resp = dlg.run()
        target = entry.get_text().strip()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and target:
            self.send_cmd("transfer", target)
            self.set_status(f"Weitergeleitet an: {target}")

    def on_switch_call_row(self, _tree, path, _col):
        self.activate_call_by_id(self.calls_store[path][0])

    def on_activate_selected_call(self, _w):
        sel = self.calls_tree.get_selection()
        model, it = sel.get_selected()
        if it:
            self.activate_call_by_id(model[it][0])

    def activate_call_by_id(self, cid):
        self.send_cmd("line", cid)
        self.send_cmd("resume")
        self.set_status(f"Aktive Leitung: ID {cid}")
        self.send_cmd("listcalls")

    def on_start_conference(self, _w):
        for cid in list(self.active_calls.keys()):
            self.send_cmd("line", cid)
            self.send_cmd("resume")
        self.send_cmd("conference")
        self.set_status("Konferenz gestartet (alle Leitungen verbunden)")

    def refresh_calls_view(self):
        self.calls_store.clear()
        for cid, info in self.active_calls.items():
            self.calls_store.append([cid, info.get("peer", ""), info.get("state", ""), info.get("dir", "")])
    def load_contacts_from_file(self):
        self.contacts_store.clear()
        if not os.path.exists(CONTACTS_FILE):
            return
        with open(CONTACTS_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'^"?([^"<]+)"?\s*<([^>]+)>', line)
                if m:
                    self.contacts_store.append([m.group(1).strip(), m.group(2).strip()])
                else:
                    self.contacts_store.append([line, line])

    def save_contacts_to_file(self):
        os.makedirs(BARESIP_DIR, exist_ok=True)
        with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
            for row in self.contacts_store:
                name, uri = row[0], row[1]
                if not uri.startswith("sip:"):
                    uri = f"sip:{uri}"
                f.write(f'"{name}" <{uri}>\n')

    def on_add_contact(self, _w):
        name = self.contact_name.get_text().strip()
        uri = self.contact_uri.get_text().strip()
        if name and uri:
            self.contacts_store.append([name, uri])
            self.save_contacts_to_file()
            self.send_cmd("addcontact", f'"{name}" <{uri}>')
            self.contact_name.set_text("")
            self.contact_uri.set_text("")

    def on_delete_contact(self, _w):
        sel = self.contacts_tree.get_selection()
        model, it = sel.get_selected()
        if it:
            model.remove(it)
            self.save_contacts_to_file()

    def on_call_contact_row(self, _tree, path, _col):
        self.entry.set_text(self.contacts_store[path][1])
        self.notebook.set_current_page(0)
        self.on_dial(False)

    def on_call_selected_contact(self, _w):
        sel = self.contacts_tree.get_selection()
        model, it = sel.get_selected()
        if it:
            self.entry.set_text(model[it][1])
            self.notebook.set_current_page(0)
            self.on_dial(False)

    def add_history(self, direction, peer):
        ts = datetime.now().strftime("%H:%M:%S")
        GLib.idle_add(self.history_store.prepend, [ts, direction, peer])

    def on_redial_row(self, _tree, path, _col):
        self.entry.set_text(self.history_store[path][2])
        self.notebook.set_current_page(0)
        self.on_dial(False)

    def on_redial_selected(self, _w):
        sel = self.history_tree.get_selection()
        model, it = sel.get_selected()
        if it:
            self.entry.set_text(model[it][2])
            self.notebook.set_current_page(0)
            self.on_dial(False)

    def on_send_message(self, _w):
        peer = self.msg_peer.get_text().strip()
        text = self.msg_input.get_text().strip()
        if peer and text:
            self.send_cmd("message", f"{peer} {text}")
            self.append_chat(f"Ich -> {peer}: {text}")
            self.msg_input.set_text("")

    def append_chat(self, line):
        def _ins():
            self.msg_buf.insert(self.msg_buf.get_end_iter(), line + "\n")
        GLib.idle_add(_ins)

    def append_sys(self, line):
        def _ins():
            self.sys_buf.insert(self.sys_buf.get_end_iter(), line + "\n")
        GLib.idle_add(_ins)

    def load_accounts_from_file(self):
        self.acc_store.clear()
        if not os.path.exists(ACCOUNTS_FILE):
            return
        with open(ACCOUNTS_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    self.acc_store.append([line])

    def save_accounts_to_file(self):
        os.makedirs(BARESIP_DIR, exist_ok=True)
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            for row in self.acc_store:
                f.write(row[0] + "\n")

    def on_save_account(self, _w):
        user = self.acc_user.get_text().strip()
        srv = self.acc_server.get_text().strip()
        pwd = self.acc_pass.get_text().strip()
        if not (user and srv and pwd):
            self.set_status("Bitte User, Server und Passwort ausfüllen!")
            return
        acc_line = f"<sip:{user}@{srv}>;auth_pass={pwd}"
        self.acc_store.append([acc_line])
        self.save_accounts_to_file()
        self.send_cmd("uanew", acc_line)
        self.acc_user.set_text("")
        self.acc_server.set_text("")
        self.acc_pass.set_text("")
        self.set_status(f"Account {user}@{srv} aktiviert")

    def on_delete_account(self, _w):
        sel = self.acc_tree.get_selection()
        model, it = sel.get_selected()
        if it:
            acc_str = model[it][0]
            m = re.search(r"<(sip:[^>]+)>", acc_str)
            if m:
                self.send_cmd("uadel", m.group(1))
            model.remove(it)
            self.save_accounts_to_file()
            self.set_status("Account entfernt")

    def on_send_raw_cmd(self, _w):
        raw = self.raw_cmd_entry.get_text().strip().lstrip("/")
        if not raw:
            return
        parts = raw.split(" ", 1)
        cmd = parts[0]
        params = parts[1] if len(parts) > 1 else ""
        self.send_cmd(cmd, params)
        self.raw_cmd_entry.set_text("")
    def send_cmd(self, command, params=""):
        if not self.sock:
            return
        payload = json.dumps({"command": command, "params": params})
        netstring = f"{len(payload)}:{payload},".encode("utf-8")
        try:
            self.sock.sendall(netstring)
        except OSError:
            self.set_status("Verbindung zu baresip verloren")

    def set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def connect_loop(self):
        while self.running:
            try:
                s = socket.create_connection((HOST, PORT), timeout=3)
                s.settimeout(None)
                self.sock = s
                self.set_status("Verbunden – Bereit")
                self.send_cmd("reginfo")
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
            while b":" in buf:
                len_str, rest = buf.split(b":", 1)
                if not len_str.isdigit():
                    buf = b""
                    break
                length = int(len_str)
                if len(rest) < length + 1:
                    break
                msg = rest[:length].decode("utf-8", errors="ignore")
                buf = rest[length + 1 :]
                self.handle_packet(msg)

    def handle_packet(self, raw_json):
        try:
            pkt = json.loads(raw_json)
        except json.JSONDecodeError:
            return

        if "response" in pkt:
            data = pkt.get("data", "").strip()
            if data:
                self.append_sys(data)
                self.parse_listcalls(data)
            return

        etype = pkt.get("type", "")
        peer = pkt.get("peeruri", "")
        cid = str(pkt.get("id", "1"))

        if etype == "CALL_INCOMING":
            self.active_calls[cid] = {"peer": peer, "state": "Klingelt", "dir": "Eingehend"}
            GLib.idle_add(self.refresh_calls_view)
            self.add_history("Eingehend", peer)
            self.set_status(f"Eingehender Anruf: {peer}")
            GLib.idle_add(self.present)

        elif etype == "CALL_OUTGOING":
            self.active_calls[cid] = {"peer": peer, "state": "Wählt...", "dir": "Ausgehend"}
            GLib.idle_add(self.refresh_calls_view)

        elif etype == "CALL_ESTABLISHED":
            self.active_calls[cid] = {"peer": peer, "state": "Verbunden", "dir": "Aktiv"}
            GLib.idle_add(self.refresh_calls_view)
            self.set_status(f"Verbunden: {peer}")

        elif etype == "CALL_CLOSED":
            self.active_calls.pop(cid, None)
            GLib.idle_add(self.refresh_calls_view)
            GLib.idle_add(self.mute_btn.set_active, False)
            GLib.idle_add(self.hold_btn.set_active, False)
            self.set_status("Anruf beendet – Bereit")

        elif etype == "REGISTER_OK":
            self.set_status(f"Registriert: {pkt.get('param', '')}")

        elif etype == "REGISTER_FAIL":
            self.set_status(f"Registrierung fehlgeschlagen: {pkt.get('param', '')}")

        elif etype == "MESSAGE":
            self.append_chat(f"{peer}: {pkt.get('param', '')}")
            self.set_status(f"Neue Nachricht von {peer}")

    def parse_listcalls(self, text):
        if "[" not in text:
            return
        for line in text.splitlines():
            m = re.search(r"\[(\d+)\]\s+(\S+)\s+\(([^)]+)\)", line)
            if m:
                self.active_calls[m.group(1)] = {
                    "peer": m.group(2), "state": m.group(3), "dir": "Aktiv"
                }
        GLib.idle_add(self.refresh_calls_view)

    def on_quit(self, _w):
        self.running = False
        if self.sock:
            self.sock.close()
        Gtk.main_quit()


if __name__ == "__main__":
    subprocess.Popen(["baresip", "-d"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = BaresipTouchApp()
    app.show_all()
    Gtk.main()
