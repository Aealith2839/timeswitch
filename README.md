# stopw

## Screenshots

| Ready | Running |
|---|---|
| ![stopw ready to start](screenshots/main.png | ![stopw countdown running](screenshots/running.png) |

A compact timer for GNOME that performs an action when the countdown ends.

stopw is written in Python using GTK 4 and libadwaita. It focuses on a
small interface, quick duration adjustments and a clear indication of
the scheduled action.

## Project status

stopw is under development.

The application currently runs from source as a standalone Python script.

The distribution goal is a ready-to-use Linux application that can be
launched from the desktop application menu without opening a terminal.
A downloadable executable distribution and a Flatpak version are planned.
The executable distribution format has not yet been selected.

Installation packages, a dedicated application icon and updated desktop
integration are not available yet.

This repository originated from Time Switch and still contains upstream
build files, metadata, translations and artwork. These files have not
yet been fully adapted to stopw.

For now, use the direct launch instructions below rather than the
inherited Time Switch build or packaging configuration.

## Features

Schedule one of the following actions:

- Power off the computer.
- Restart the computer.
- Suspend the computer.
- Show a notification, optionally with a sound.
- Run a custom shell command.

The interface includes:

- An editable hours/minutes/seconds display.
- Mouse-wheel and keyboard controls.
- A readable action label during the countdown.
- A Stop button to cancel the countdown.
- A reset button and a Delete-key shortcut.
- Optional restoration of the last started duration and selected action.
- Support for the system light/dark appearance preference.

## Requirements

The current implementation targets Linux systems using systemd for
power-management actions.

Required components:

- Python 3.
- PyGObject with GTK 4 and libadwaita introspection bindings.
- GTK 4.10 or newer.
- A libadwaita version providing Adw.AboutWindow.

GTK 4.10 is required because the sound-file chooser uses Gtk.FileDialog.

Additional host commands are required for the corresponding actions:

| Feature | Required command |
| --- | --- |
| Power off, restart and suspend | systemctl |
| Desktop notifications | notify-send |
| Default or custom notification sound | canberra-gtk-play |
| Custom shell commands | /bin/sh and the programs used by the command |

System permissions, session policies and the availability of these
commands can affect whether an action succeeds.

An exact minimum Python/libadwaita version and a distribution support
matrix have not yet been established.

## Run from source

Open a terminal in the repository directory and run:

```sh
python3 stopw.py
```

Run the application as your normal desktop user, not as root.

The countdown is managed by the running application. It is not installed
as a background system task.

## Usage

1. Set a duration.
2. Select an action from the Action menu.
3. Configure notification settings or a custom command if needed.
4. Press Start.

While the countdown is running, its duration and selected action cannot
be edited. Press Stop to cancel it and retain the displayed remaining
time.

Closing the main window cancels the countdown.

### Timer controls

- Click a numeric pair to select hours, minutes or seconds.
- Scroll over the timer to adjust the selected pair.
- If no pair is selected, scrolling adjusts the minutes.
- Type digits to enter a value.
- Use Left and Right to move between pairs.
- Use Up and Down to adjust the selected pair.
- Use Backspace to clear the selected pair.
- Selection highlighting disappears after five seconds without interaction.

After selection expires, scrolling targets the minutes again. Fresh
numeric keyboard entry starts with the hours.

### Reset

Use the reset button in the header bar, or press Delete while the main
window is active.

Reset is unavailable during a countdown. Stop the countdown first.

Reset clears the displayed duration without changing the selected action
or the previously saved starting duration.

### Saved preferences

The application menu contains two independent preferences, enabled by
default:

- Save timer.
- Save action.

Save timer restores the duration most recently used to start a countdown,
not the remaining time when a countdown was stopped.

Save action restores the selected action.

Disabling either preference removes its stored restoration value without
changing the current display. Restoring a duration never starts a
countdown automatically.

Settings are currently stored in:

```text
~/.config/stopw/config.ini
```

Notification settings and custom command text are stored independently
of these two preferences.

### Custom commands

Choose Command from the Action menu to open the command editor.

Saving a nonempty command selects the Command action. Saving does not
execute it. Closing the editor without saving leaves the previous
command and action unchanged.

At the end of the countdown, the saved command is passed to:

```sh
/bin/sh -c 'your command'
```

The application does not add privilege elevation or open an interactive
terminal. Commands run with the current user's permissions and inherit
the application's environment and working directory.

Shell features such as pipes and redirections are available. Commands
must be compatible with /bin/sh; Bash-specific syntax is not guaranteed.

Only enter commands you understand and trust. The command is stored as
plain text in the configuration file. Do not use this field to store
passwords, access tokens or other secrets.

## Translations

The source interface language is French.

The application is prepared for gettext translations and looks for
compiled catalogs at:

```text
locale/<language>/LC_MESSAGES/stopw.mo
```

If no matching catalog is available, it falls back to the French source
strings.

The inherited Time Switch translation files have not yet been adapted
to stopw. Their presence does not mean translated stopw interfaces are
currently available.

## Known limitations

- Child-process launch errors are printed to the terminal, but command
  exit status and action failures are not yet reported in the interface.
- Countdown behavior across system suspend/resume has not yet been
  formally specified and tested.
- With no explicitly restored or selected action, the current internal
  default is power off, even if the selector displays "Action".
  Always select and verify an action before starting a timer.
- Flatpak and other installation configurations inherited from Time Switch
  have not been adapted or validated for stopw.
- The dedicated icon, packaging and automated test coverage remain work
  in progress.

For initial testing, use a notification or a harmless custom command
rather than a power-management action.

## Reporting problems

Use this repository's issue tracker.

Please include:

- Your Linux distribution and version.
- Your desktop environment.
- Your Python, GTK and libadwaita versions, if known.
- Steps to reproduce the problem.
- Relevant terminal output, with personal information and secrets removed.

## Origins and credits

stopw originated from a fork of
[Time Switch](https://github.com/fsobolev/timeswitch)
by Fyodor Sobolev.

It is developed independently and is not an official Time Switch release.

See [CREDITS.md](CREDITS.md) for provenance and development credits.

## License

New stopw contributions are licensed under the GNU General Public License,
version 3 only (SPDX: GPL-3.0-only).

See [COPYING](COPYING) for the complete GPLv3 text and
[LICENSING.md](LICENSING.md) for the licensing details.

Material inherited from Time Switch retains its original notices.
The original license text is preserved in
[LICENSES/TimeSwitch-original.txt](LICENSES/TimeSwitch-original.txt).
