#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-only
#
# Copyright (C) 2026 Aealith2839
#
# stopw originated from Time Switch by Fyodor Sobolev.
# The interface and behavior were redesigned for stopw in 2026.
# See CREDITS.md, LICENSING.md and LICENSES/TimeSwitch-original.txt
# for provenance and the terms covering inherited material.
#
# The new stopw contributions are free software: you can redistribute
# them and/or modify them under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 3.
#
# stopw is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with stopw. If not, see <https://www.gnu.org/licenses/>.

"""stopw: a small GTK timer that performs an action when its countdown ends.

Runtime dependencies include PyGObject, GTK 4.10 or newer and libadwaita.
External actions also require their respective host commands (systemctl,
notify-send and canberra-gtk-play). Custom commands are interpreted by /bin/sh.

Translation catalogs are loaded from locale/<language>/LC_MESSAGES/stopw.mo.

New stopw contributions are licensed under GPL-3.0-only.
See COPYING, LICENSING.md and CREDITS.md for licensing and provenance.
The original Time Switch license is preserved in LICENSES/TimeSwitch-original.txt.
"""

import sys
import os
import gettext
import configparser
import subprocess
import gi

# Select introspection namespaces before importing their Python bindings.
# These are API major versions, not the minimum minor versions we require.
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gtk, Gio, GLib, Gdk

APP_ID = "org.eric.stopw"
APP_NAME = "stopw"
CONFIG_DIR = os.path.expanduser("~/.config/stopw")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCALE_DIR = os.path.join(BASE_DIR, "locale")
SELECTION_TIMEOUT_SECONDS = 5
MAX_TIMER_SECONDS = 99 * 3600 + 59 * 60 + 59

# French is the source language. Missing catalogs fall back to source strings.
# Keep complete sentences in catalogs rather than concatenating translated words.
translation = gettext.translation(APP_NAME, localedir=LOCALE_DIR, fallback=True)
_ = translation.gettext


def read_config():
    """Read user settings without interpreting percent signs in shell commands."""
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read(CONFIG_FILE, encoding="utf-8")
    except (OSError, configparser.Error) as error:
        print(f"Configuration read error: {error}", file=sys.stderr)
        config = configparser.ConfigParser(interpolation=None)
    if not config.has_section("Settings"):
        config.add_section("Settings")
    return config


def write_config(config):
    """Replace the settings file after writing a complete temporary copy.

    This avoids partially overwriting the previous file during an ordinary
    interrupted write. It is not a full power-loss durability guarantee.
    """
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        temporary_file = CONFIG_FILE + ".tmp"
        with open(temporary_file, "w", encoding="utf-8") as file:
            config.write(file)
        os.replace(temporary_file, CONFIG_FILE)
    except (OSError, configparser.Error) as error:
        print(f"Configuration save error: {error}", file=sys.stderr)


def get_boolean(config, key, default):
    """Use a safe default if a preference is missing or malformed."""
    try:
        return config.getboolean("Settings", key, fallback=default)
    except ValueError:
        return default


def get_integer(config, key, default=0):
    """Do not let an invalid saved duration prevent startup."""
    try:
        return config.getint("Settings", key, fallback=default)
    except ValueError:
        return default


class NotificationDialog(Adw.Window):
    """Edit notification settings without changing them until Save is pressed."""

    def __init__(self, parent, current_text, sound_mode,
                 custom_sound_path, on_save_callback):
        super().__init__(transient_for=parent)
        # The internal window title is retained for window management. No
        # HeaderBar is added, matching the existing titlebar-free presentation.
        self.set_title(_("Paramètres de notification"))
        self.set_modal(True)
        self.set_default_size(380, 360)
        self.set_resizable(False)
        self.on_save_callback = on_save_callback
        self.custom_sound_path = custom_sound_path

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main_box.set_margin_top(18)
        main_box.set_margin_bottom(18)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        self.set_content(main_box)

        description = Gtk.Label(
            label=_("Personnalisez l'alerte de fin de décompte :"))
        description.set_halign(Gtk.Align.START)
        main_box.append(description)
        self.text_entry = Gtk.Entry()
        self.text_entry.set_placeholder_text(
            _("Message de notification (optionnel)..."))
        self.text_entry.set_text(current_text)
        main_box.append(self.text_entry)

        # Individual gaps preserve the middle option's position while bringing
        # the outer options closer. The bottom controls keep their positions.
        group_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        group_box.set_margin_top(6)
        sound_label = Gtk.Label(label=_("Signal sonore :"))
        sound_label.set_halign(Gtk.Align.START)
        sound_label.set_margin_bottom(10)
        group_box.append(sound_label)

        self.radio_none = Gtk.CheckButton(label=_("Aucun son"))
        self.radio_none.set_margin_bottom(4)
        group_box.append(self.radio_none)
        self.radio_default = Gtk.CheckButton(
            label=_("Bip système par défaut"), group=self.radio_none)
        self.radio_default.set_margin_bottom(4)
        group_box.append(self.radio_default)
        self.radio_custom = Gtk.CheckButton(
            label=_("Fichier audio personnalisé"), group=self.radio_none)
        self.radio_custom.set_margin_bottom(16)
        group_box.append(self.radio_custom)
        for radio in (self.radio_none, self.radio_default, self.radio_custom):
            radio.add_css_class("notification-option")

        file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.btn_file = Gtk.Button(label=_("Parcourir..."))
        self.btn_file.connect("clicked", self.on_browse_clicked)
        file_box.append(self.btn_file)
        self.lbl_filename = Gtk.Label(label=(
            os.path.basename(custom_sound_path) if custom_sound_path
            else _("Aucun fichier sélectionné")))
        self.lbl_filename.add_css_class("dim-label")
        file_box.append(self.lbl_filename)
        group_box.append(file_box)
        main_box.append(group_box)

        # Grouped CheckButtons behave as mutually exclusive radio choices.
        self.radio_custom.connect(
            "toggled", lambda button: self.set_custom_active(button.get_active()))
        if sound_mode == "none":
            self.radio_none.set_active(True)
        elif sound_mode == "custom":
            self.radio_custom.set_active(True)
        else:
            self.radio_default.set_active(True)
        self.set_custom_active(self.radio_custom.get_active())

        save_button = Gtk.Button(label=_("Enregistrer"))
        save_button.add_css_class("suggested-action")
        save_button.set_margin_top(10)
        save_button.connect("clicked", self.on_save_clicked)
        main_box.append(save_button)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

    def on_key_pressed(self, controller, keyval, keycode, state):
        """Escape discards unsaved changes."""
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def set_custom_active(self, active):
        self.btn_file.set_sensitive(active)
        self.lbl_filename.set_visible(active)

    def on_browse_clicked(self, button):
        # FileDialog is asynchronous: its result must be collected in a callback.
        dialog = Gtk.FileDialog.new()
        dialog.set_title(_("Sélectionner un son"))
        dialog.open(self, None, self.on_file_selected)

    def on_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file is None:
                return
            path = file.get_path()
            # The current playback backend expects a local filesystem path.
            if path:
                self.custom_sound_path = path
                self.lbl_filename.set_text(os.path.basename(path))
        except GLib.Error as error:
            if (error.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED)
                    or error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)):
                return
            print(f"File selection error: {error}", file=sys.stderr)

    def on_save_clicked(self, button):
        mode = ("none" if self.radio_none.get_active() else
                "custom" if self.radio_custom.get_active() else "default")
        self.on_save_callback(
            self.text_entry.get_text(), mode, self.custom_sound_path)
        self.close()


class CommandDialog(Adw.Window):
    """Collect a shell command; saving never executes it."""

    def __init__(self, parent, current_command, on_save_callback):
        super().__init__(transient_for=parent)
        self.set_title(_("Commande personnalisée"))
        self.set_modal(True)
        self.set_default_size(380, 170)
        self.set_resizable(False)
        self.on_save_callback = on_save_callback

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main_box.set_margin_top(18)
        main_box.set_margin_bottom(18)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        self.set_content(main_box)
        label = Gtk.Label(label=_("Votre commande :"))
        label.set_halign(Gtk.Align.START)
        main_box.append(label)

        self.command_entry = Gtk.Entry()
        self.command_entry.set_hexpand(True)
        # Zero means no additional application-defined character limit.
        self.command_entry.set_max_length(0)
        self.command_entry.set_text(current_command)
        self.command_entry.set_tooltip_text(_(
            "Exécutée avec /bin/sh à la fin du décompte, "
            "avec vos droits utilisateur."))
        main_box.append(self.command_entry)

        self.save_button = Gtk.Button(label=_("Enregistrer"))
        self.save_button.add_css_class("suggested-action")
        self.save_button.set_margin_top(10)
        self.save_button.connect("clicked", self.on_save_clicked)
        main_box.append(self.save_button)
        self.command_entry.connect("changed", self.on_command_changed)
        self.command_entry.connect("activate", self.on_entry_activate)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)
        self.on_command_changed(self.command_entry)

    def on_command_changed(self, entry):
        self.save_button.set_sensitive(bool(entry.get_text().strip()))

    def on_entry_activate(self, entry):
        if self.save_button.get_sensitive():
            self.on_save_clicked(self.save_button)

    def on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def on_save_clicked(self, button):
        command = self.command_entry.get_text()
        if not command.strip():
            return
        # Validate emptiness without stripping or rewriting the saved command.
        self.on_save_callback(command)
        self.close()


class StopwWindow(Adw.ApplicationWindow):
    """Main UI, editable timer state, selection timeout and countdown lifecycle."""

    def __init__(self, application):
        super().__init__(application=application)
        self.set_size_request(240, 250)
        self.set_resizable(False)
        self.action_labels = {
            "shutdown": _("Éteindre"), "reboot": _("Redémarrer"),
            "suspend": _("Veille"), "notify": _("Notification"),
            "custom": _("Commande"),
        }
        self.running_action_labels = {
            "shutdown": _("Avant arrêt"), "reboot": _("Avant redémarrage"),
            "suspend": _("Avant veille"), "notify": _("Avant notification"),
            "custom": _("Avant commande"),
        }
        # A non-None source ID means that its GLib callback is registered.
        self.timer_source_id = None
        self.selection_source_id = None
        self.remaining_seconds = 0
        self.deadline = None
        self.active_field = None
        self.typing_buffer = ""
        self.load_settings()

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_title_widget(Gtk.Label(label=""))
        self.reset_button = Gtk.Button()
        self.reset_button.set_icon_name("view-refresh-symbolic")
        self.reset_button.set_tooltip_text(_("Remettre à zéro (Suppr)"))
        self.reset_button.set_action_name("app.reset_timer")
        header.pack_start(self.reset_button)

        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu = Gio.Menu()
        preferences = Gio.Menu()
        preferences.append(_("Sauvegarder timer"), "app.remember_timer")
        preferences.append(_("Sauvegarder action"), "app.remember_action")
        menu.append_section(None, preferences)
        about_section = Gio.Menu()
        about_section.append(_("À propos de stopw"), "app.about")
        menu.append_section(None, about_section)
        menu_button.set_menu_model(menu)
        header.pack_start(menu_button)
        main_box.append(header)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(14)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        main_box.append(content_box)

        self.time_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.time_container.set_halign(Gtk.Align.CENTER)
        self.time_container.set_hexpand(True)
        self.time_container.set_focusable(True)
        self.time_container.add_css_class("time-box")
        self.lbl_hours = Gtk.Label(label="00")
        self.lbl_mins = Gtk.Label(label="00")
        self.lbl_secs = Gtk.Label(label="00")
        for label in (self.lbl_hours, self.lbl_mins, self.lbl_secs):
            label.add_css_class("time-part")
        colon1 = Gtk.Label(label=":")
        colon2 = Gtk.Label(label=":")
        for colon in (colon1, colon2):
            colon.add_css_class("time-colon")
        for widget in (self.lbl_hours, colon1, self.lbl_mins, colon2, self.lbl_secs):
            self.time_container.append(widget)

        click = Gtk.GestureClick()
        click.set_button(Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self.on_time_clicked)
        self.time_container.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_time_key_pressed)
        self.time_container.add_controller(keys)
        scroll = Gtk.EventControllerScroll()
        # Discrete mode turns smooth device movement into individual steps.
        scroll.set_flags(Gtk.EventControllerScrollFlags.VERTICAL |
                         Gtk.EventControllerScrollFlags.DISCRETE)
        scroll.connect("scroll", self.on_time_scroll)
        self.time_container.add_controller(scroll)
        content_box.append(self.time_container)

        initial_label = (self.action_labels[self.current_action]
                         if self.action_selected_explicitly else _("Action"))
        self.action_button = Gtk.MenuButton(label=initial_label)
        self.action_button.set_halign(Gtk.Align.FILL)
        self.action_button.add_css_class("action-button")
        self.action_button.set_has_frame(True)
        self.action_button.set_size_request(-1, 42)
        action_menu = Gio.Menu()
        for label, action in (
            (_("Éteindre"), "app.set_action_shutdown"),
            (_("Redémarrer"), "app.set_action_reboot"),
            (_("Mettre en veille"), "app.set_action_suspend"),
            (_("Notification / Son"), "app.set_action_notify"),
            (_("Configurer la notif..."), "app.configure_notify"),
            (_("Commande..."), "app.set_action_custom"),
        ):
            action_menu.append(label, action)
        self.action_button.set_menu_model(action_menu)

        self.running_action_label = Gtk.Label(
            label=self.running_action_labels[self.current_action])
        self.running_action_label.add_css_class("running-action-label")
        self.running_action_label.set_halign(Gtk.Align.FILL)
        self.running_action_label.set_valign(Gtk.Align.CENTER)
        self.running_action_label.set_xalign(0.5)
        self.running_action_label.set_yalign(0.5)
        self.running_action_label.set_size_request(-1, 42)
        self.running_action_label.set_margin_start(8)
        self.running_action_label.set_margin_end(8)

        # The idle page keeps Action near Start. The running page centers its
        # label in the same expanding area, without moving the lower button.
        selection_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        selection_box.append(spacer)
        self.action_button.set_valign(Gtk.Align.END)
        selection_box.append(self.action_button)
        self.action_stack = Gtk.Stack()
        self.action_stack.set_hhomogeneous(True)
        self.action_stack.set_vhomogeneous(True)
        self.action_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.action_stack.set_halign(Gtk.Align.FILL)
        self.action_stack.set_valign(Gtk.Align.FILL)
        self.action_stack.set_vexpand(True)
        self.action_stack.add_named(selection_box, "selection")
        self.action_stack.add_named(self.running_action_label, "running")
        self.action_stack.set_visible_child_name("selection")
        content_box.append(self.action_stack)

        self.start_button = Gtk.Button(label=_("Commencer"))
        self.start_button.set_halign(Gtk.Align.FILL)
        self.start_button.add_css_class("orange-button")
        self.start_button.set_size_request(-1, 42)
        self.start_button.connect("clicked", self.on_start_clicked)
        content_box.append(self.start_button)

        # The main-window shortcut is independent of pointer location. Modal
        # editor windows receive their own key events, not this shortcut.
        window_keys = Gtk.EventControllerKey()
        window_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        window_keys.connect("key-pressed", self.on_window_key_pressed)
        self.add_controller(window_keys)
        self.connect("close-request", self.on_close_request)
        self.update_time_display()

    def load_settings(self):
        """Restore preferences but never automatically start a countdown."""
        app = self.get_application()
        config = app.config
        self.custom_command = config.get("Settings", "custom_command", fallback="")
        saved_action = config.get("Settings", "last_action", fallback="shutdown")
        if saved_action not in self.action_labels:
            saved_action = "shutdown"
        self.current_action = saved_action if app.remember_action else "shutdown"
        self.action_selected_explicitly = (
            get_boolean(config, "explicitly_selected", False)
            if app.remember_action else False)
        if self.current_action == "custom" and not self.custom_command.strip():
            self.current_action = "shutdown"
            self.action_selected_explicitly = False
        total = (get_integer(config, "last_timer_seconds", 0)
                 if app.remember_timer else 0)
        total = max(0, min(MAX_TIMER_SECONDS, total))
        self.hours = total // 3600
        self.minutes = (total % 3600) // 60
        self.seconds = total % 60
        self.notif_text = config.get(
            "Settings", "notif_text", fallback=_("Minuteur terminé !"))
        self.notif_sound = config.get("Settings", "notif_sound", fallback="default")
        self.custom_sound = config.get("Settings", "custom_sound", fallback="")

    def total_seconds(self):
        return self.hours * 3600 + self.minutes * 60 + self.seconds

    def is_running(self):
        return self.timer_source_id is not None

    def has_valid_action(self):
        return self.current_action != "custom" or bool(self.custom_command.strip())

    def update_time_display(self):
        """Refresh numbers, selection styling and control availability together."""
        for index, (label, value) in enumerate(zip(
                (self.lbl_hours, self.lbl_mins, self.lbl_secs),
                (self.hours, self.minutes, self.seconds),
        )):
            label.set_text(f"{value:02d}")
            if index == self.active_field:
                label.add_css_class("active")
            else:
                label.remove_css_class("active")

        self.start_button.set_sensitive(
            self.is_running() or (
                self.total_seconds() > 0
                and self.action_selected_explicitly
                and self.has_valid_action()
            )
        )
        self.update_action_availability()

    def update_action_availability(self):
        app = self.get_application()
        idle = not self.is_running()
        for name in self.action_labels:
            app.lookup_action(f"set_action_{name}").set_enabled(idle)
        app.lookup_action("configure_notify").set_enabled(idle)
        app.lookup_action("reset_timer").set_enabled(idle and self.total_seconds() > 0)

    def select_action(self, action_type):
        if self.is_running():
            return
        self.current_action = action_type
        self.action_selected_explicitly = True
        self.action_button.set_label(self.action_labels[action_type])
        self.save_action()
        self.update_time_display()

    def save_action(self):
        app = self.get_application()
        if not app.remember_action:
            return
        app.config.set("Settings", "last_action", self.current_action)
        app.config.set("Settings", "explicitly_selected",
                       str(self.action_selected_explicitly).lower())
        write_config(app.config)

    def save_timer(self, total_seconds):
        # Persist the starting duration, never the remaining time at Stop.
        app = self.get_application()
        if app.remember_timer:
            app.config.set("Settings", "last_timer_seconds", str(total_seconds))
            write_config(app.config)

    def cancel_selection_timeout(self):
        if self.selection_source_id is not None:
            GLib.source_remove(self.selection_source_id)
            self.selection_source_id = None

    def restart_selection_timeout(self):
        self.cancel_selection_timeout()
        if not self.is_running() and self.active_field is not None:
            self.selection_source_id = GLib.timeout_add(
                SELECTION_TIMEOUT_SECONDS * 1000, self.on_selection_timeout)

    def on_selection_timeout(self):
        # The callback removes itself by returning False. Clear the ID first.
        self.selection_source_id = None
        self.active_field = None
        self.typing_buffer = ""
        self.update_time_display()
        return False

    def clear_selection(self):
        self.cancel_selection_timeout()
        self.active_field = None
        self.typing_buffer = ""

    def on_time_clicked(self, gesture, n_press, x, y):
        if self.is_running():
            return
        self.time_container.grab_focus()
        centers = []
        for label in (self.lbl_hours, self.lbl_mins, self.lbl_secs):
            allocation = label.get_allocation()
            centers.append(allocation.x + allocation.width / 2)
        # Boundaries fall halfway between adjacent numeric pairs.
        if x < (centers[0] + centers[1]) / 2:
            self.active_field = 0
        elif x < (centers[1] + centers[2]) / 2:
            self.active_field = 1
        else:
            self.active_field = 2
        self.typing_buffer = ""
        self.restart_selection_timeout()
        self.update_time_display()

    def change_active_field(self, delta):
        if self.is_running():
            return
        if self.active_field is None:
            self.active_field = 1  # Minutes are the default scroll target.
        self.typing_buffer = ""
        if self.active_field == 0:
            self.hours = max(0, min(99, self.hours + delta))
        elif self.active_field == 1:
            self.minutes = max(0, min(59, self.minutes + delta))
        else:
            self.seconds = max(0, min(59, self.seconds + delta))
        self.restart_selection_timeout()
        self.update_time_display()

    def on_time_key_pressed(self, controller, keyval, keycode, state):
        if self.is_running():
            return False
        modifiers = (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK |
                     Gdk.ModifierType.SUPER_MASK)
        if state & modifiers:
            return False
        digit = None
        if Gdk.KEY_0 <= keyval <= Gdk.KEY_9:
            digit = keyval - Gdk.KEY_0
        elif Gdk.KEY_KP_0 <= keyval <= Gdk.KEY_KP_9:
            digit = keyval - Gdk.KEY_KP_0
        if digit is not None:
            # Fresh keyboard entry starts with hours; scrolling defaults to minutes.
            if self.active_field is None:
                self.active_field = 0
            self.typing_buffer += str(digit)
            value = int(self.typing_buffer)
            if self.active_field == 0:
                self.hours = min(99, value)
            elif self.active_field == 1:
                self.minutes = min(59, value)
            else:
                self.seconds = min(59, value)
            if (len(self.typing_buffer) >= 2 or
                    (self.active_field != 0 and value > 5)):
                self.typing_buffer = ""
                if self.active_field < 2:
                    self.active_field += 1
        elif keyval == Gdk.KEY_BackSpace:
            self.typing_buffer = ""
            if self.active_field == 0:
                self.hours = 0
            elif self.active_field == 1:
                self.minutes = 0
            elif self.active_field == 2:
                self.seconds = 0
            else:
                return False
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            if self.active_field is None:
                self.active_field = 1
            else:
                delta = -1 if keyval == Gdk.KEY_Left else 1
                self.active_field = max(0, min(2, self.active_field + delta))
            self.typing_buffer = ""
        elif keyval == Gdk.KEY_Up:
            self.change_active_field(1)
            return True
        elif keyval == Gdk.KEY_Down:
            self.change_active_field(-1)
            return True
        else:
            return False
        self.restart_selection_timeout()
        self.update_time_display()
        return True

    def on_time_scroll(self, controller, dx, dy):
        if self.is_running() or dy == 0:
            return False
        self.time_container.grab_focus()
        steps = max(1, int(round(abs(dy))))
        self.change_active_field(steps if dy < 0 else -steps)
        return True

    def on_window_key_pressed(self, controller, keyval, keycode, state):
        if keyval not in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            return False
        if not self.is_active() or self.is_running():
            return False
        modifiers = (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK |
                     Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.SHIFT_MASK)
        if state & modifiers:
            return False
        # Future editable widgets must retain their ordinary Delete behavior.
        if isinstance(self.get_focus(), (Gtk.Editable, Gtk.TextView)):
            return False
        self.reset_timer()
        return True

    def reset_timer(self):
        """Clear only the displayed duration, not the action or saved duration."""
        if self.is_running():
            return
        self.clear_selection()
        self.hours = self.minutes = self.seconds = self.remaining_seconds = 0
        self.update_time_display()

    def on_start_clicked(self, button):
        if self.is_running():
            self.stop_timer()
            return

        total = self.total_seconds()
        if (total <= 0
                or not self.action_selected_explicitly
                or not self.has_valid_action()):
            return

        self.clear_selection()
        self.remaining_seconds = total

        # A monotonic deadline avoids accumulating GLib callback delays.
        # Suspend/resume semantics still need explicit testing and policy.
        self.deadline = GLib.get_monotonic_time() + total * 1_000_000
        self.start_button.set_label(_("Stop"))
        self.start_button.remove_css_class("orange-button")
        self.start_button.add_css_class("red-button")
        self.running_action_label.set_text(
            self.running_action_labels[self.current_action])
        self.action_button.set_sensitive(False)
        self.action_stack.set_visible_child_name("running")
        self.save_timer(total)
        self.save_action()
        self.timer_source_id = GLib.timeout_add(100, self.on_timer_tick)
        self.update_time_display()

    def on_timer_tick(self):
        remaining_us = max(0, self.deadline - GLib.get_monotonic_time())
        # Round up so the displayed timer does not show zero prematurely.
        remaining = (remaining_us + 999_999) // 1_000_000
        if remaining != self.remaining_seconds:
            self.remaining_seconds = remaining
            self.hours = remaining // 3600
            self.minutes = (remaining % 3600) // 60
            self.seconds = remaining % 60
            self.update_time_display()
        if remaining == 0:
            # Returning False removes this callback; do not remove it twice.
            self.timer_source_id = None
            self.stop_timer()
            self.trigger_action()
            return False
        return True

    def stop_timer(self):
        """Cancel a running timer while retaining its displayed remaining time."""
        if self.timer_source_id is not None:
            GLib.source_remove(self.timer_source_id)
            self.timer_source_id = None
        self.deadline = None
        self.clear_selection()
        self.start_button.set_label(_("Commencer"))
        self.start_button.remove_css_class("red-button")
        self.start_button.add_css_class("orange-button")
        self.action_button.set_sensitive(True)
        self.action_stack.set_visible_child_name("selection")
        self.update_time_display()

    def run_command(self, arguments):
        """Start a child without blocking GTK.

        Launch errors are reported to stderr. Child exit codes are not yet
        monitored or shown in the UI; successful launch is not successful action.
        """
        try:
            subprocess.Popen(arguments)
        except (OSError, ValueError) as error:
            print(f"Unable to launch {arguments[0]}: {error}", file=sys.stderr)

    def trigger_action(self):
        """Dispatch exactly once when the countdown reaches zero."""
        if self.current_action == "shutdown":
            self.run_command(["systemctl", "poweroff"])
        elif self.current_action == "reboot":
            self.run_command(["systemctl", "reboot"])
        elif self.current_action == "suspend":
            self.run_command(["systemctl", "suspend"])
        elif self.current_action == "notify":
            if self.notif_text.strip():
                self.run_command(["notify-send", APP_NAME, self.notif_text])
            if self.notif_sound == "default":
                self.run_command(["canberra-gtk-play", "--id=complete"])
            elif (self.notif_sound == "custom" and self.custom_sound
                  and os.path.isfile(self.custom_sound)):
                self.run_command(["canberra-gtk-play", "--file=" + self.custom_sound])
        elif self.current_action == "custom" and self.custom_command.strip():
            # Shell interpretation is intentional for user-authored commands.
            # It permits pipes/redirections and grants the command all privileges
            # already held by this user. Never silently insert untrusted text.
            self.run_command(["/bin/sh", "-c", self.custom_command])

    def on_close_request(self, window):
        self.cancel_selection_timeout()
        if self.timer_source_id is not None:
            GLib.source_remove(self.timer_source_id)
            self.timer_source_id = None
        self.deadline = None
        # Closing cancels the timer; it does not leave a background scheduler.
        self.get_application().window = None
        return False


class StopwApp(Adw.Application):
    """Own settings, shared Gio actions and the single main window."""

    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None
        self.config = read_config()
        self.remember_timer = get_boolean(self.config, "remember_timer", True)
        self.remember_action = get_boolean(self.config, "remember_action", True)
        for name, callback in (
            ("about", self.show_about),
            ("configure_notify", self.show_notify_config),
            ("reset_timer", self.on_reset_timer),
        ):
            self.add_simple_action(name, callback)
        for name in ("shutdown", "reboot", "suspend", "notify", "custom"):
            action = Gio.SimpleAction.new(f"set_action_{name}", None)
            action.connect("activate", self.on_action_selected, name)
            self.add_action(action)
        self.add_boolean_action("remember_timer", self.remember_timer)
        self.add_boolean_action("remember_action", self.remember_action)

    def add_simple_action(self, name, callback):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

    def add_boolean_action(self, name, initial_value):
        # Boolean action state supplies the menu's native checked appearance.
        action = Gio.SimpleAction.new_stateful(
            name, None, GLib.Variant("b", initial_value))
        action.connect("activate", self.on_preference_activated)
        action.connect("change-state", self.on_preference_changed)
        self.add_action(action)

    def on_preference_activated(self, action, parameter):
        action.change_state(GLib.Variant("b", not action.get_state().get_boolean()))

    def on_preference_changed(self, action, value):
        enabled = value.get_boolean()
        name = action.get_name()
        action.set_state(value)
        self.config.set("Settings", name, str(enabled).lower())
        if name == "remember_timer":
            self.remember_timer = enabled
            if not enabled:
                self.config.remove_option("Settings", "last_timer_seconds")
        elif name == "remember_action":
            self.remember_action = enabled
            if not enabled:
                self.config.remove_option("Settings", "last_action")
                self.config.remove_option("Settings", "explicitly_selected")
            elif self.window is not None:
                self.config.set("Settings", "last_action", self.window.current_action)
                self.config.set("Settings", "explicitly_selected",
                                str(self.window.action_selected_explicitly).lower())
        write_config(self.config)

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Follow the system preference; ordinary text inherits theme colors.
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .time-box { background: transparent; padding: 4px 0px; }
            .time-part {
                font-family: Cantarell, sans-serif;
                font-variant-numeric: tabular-nums;
                font-feature-settings: "tnum";
                font-size: 38px; font-weight: bold; opacity: 0.7;
            }
            .time-part.active { opacity: 1.0; }
            .time-colon {
                font-family: Cantarell, sans-serif;
                font-size: 38px; font-weight: bold;
                opacity: 0.7; padding: 0px 4px;
            }
            checkbutton.notification-option > label { margin-left: 12px; }
            .action-button { font-size: 15px; font-weight: bold; }
            .action-button > button { border-radius: 10px; }
            .running-action-label { font-size: 15px; font-weight: bold; }
            .orange-button {
                background-image: none; background-color: #e66100;
                color: #ffffff; font-size: 16px; font-weight: bold;
                border-radius: 10px;
            }
            .orange-button:hover { background-color: #ff781f; }
            .orange-button:disabled {
                background-color: #e66100; color: #ffffff; opacity: 0.45;
            }
            .red-button {
                background-image: none; background-color: #c01c28;
                color: #ffffff; font-size: 16px; font-weight: bold;
                border-radius: 10px;
            }
            .red-button:hover { background-color: #e01b24; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if self.window is None:
            self.window = StopwWindow(application=self)
        self.window.present()

    def on_action_selected(self, action, parameter, action_type):
        if self.window is None or self.window.is_running():
            return
        if action_type == "custom":
            # Do not select Custom until a nonempty command has been saved.
            self.show_command_config()
        else:
            self.window.select_action(action_type)

    def on_reset_timer(self, action, parameter):
        if self.window is not None:
            self.window.reset_timer()

    def show_notify_config(self, action, parameter):
        window = self.window
        if window is None or window.is_running():
            return
        dialog = NotificationDialog(
            parent=window, current_text=window.notif_text,
            sound_mode=window.notif_sound, custom_sound_path=window.custom_sound,
            on_save_callback=lambda text, mode, path:
                self.save_notify_config(window, text, mode, path))
        dialog.present()

    def save_notify_config(self, window, text, mode, path):
        window.notif_text = text
        window.notif_sound = mode
        window.custom_sound = path or ""
        self.config.set("Settings", "notif_text", text)
        self.config.set("Settings", "notif_sound", mode)
        self.config.set("Settings", "custom_sound", window.custom_sound)
        write_config(self.config)

    def show_command_config(self):
        window = self.window
        if window is None or window.is_running():
            return
        dialog = CommandDialog(
            parent=window, current_command=window.custom_command,
            on_save_callback=lambda command: self.save_command_config(window, command))
        dialog.present()
        dialog.command_entry.grab_focus()

    def save_command_config(self, window, command):
        if window.is_running() or not command.strip():
            return
        window.custom_command = command
        # Keep command content even when remembering the selected action is off.
        self.config.set("Settings", "custom_command", command)
        write_config(self.config)
        window.select_action("custom")

    def show_about(self, action, parameter):
        about = Adw.AboutWindow(
            transient_for=self.window, application_name=APP_NAME,
            application_icon="time-symbolic", developer_name="Eric",
            version="0.1.0", comments=_("Minuteur épuré pour GNOME"),
            # Display the license selected for the new stopw contributions.
            # Upstream notices are preserved separately; see LICENSING.md.
            license_type=Gtk.License.GPL_3_0)
        about.present()


if __name__ == "__main__":
    app = StopwApp()
    sys.argv[0] = APP_NAME
    sys.exit(app.run(sys.argv))

