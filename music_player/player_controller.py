from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from music_player.models import Track, collect_audio_paths
from music_player.persistence import AppState
from music_player.streaming import FfmpegStreamManager
from music_player.system_integration import shutdown_windows, sleep_windows

# Max plausible forward jump between two positionChanged events that still
# counts as real listening. Normal ticks are well under a second; anything
# larger is a seek or a track change and must not be added to listen time.
_MAX_LISTEN_DELTA_MS = 3_000

# How long after the scheduled time the action may still fire. Past this
# window the moment was missed (PC was asleep / powered off), and executing
# a stale sleep/shutdown right after the user wakes the machine would be
# hostile — cancel instead.
_SCHEDULED_GRACE_S = 180

# Kolko skladieb ma zostat do konca playlistu po stlaceni tlacidla "Spanok".
_SLEEP_TAIL_TRACKS = 3


class PlayerController(QObject):
    playlist_changed = Signal()
    recent_tracks_changed = Signal()
    current_track_changed = Signal(object)
    playback_state_changed = Signal(str)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    volume_changed = Signal(int)
    message_emitted = Signal(str)
    audio_outputs_changed = Signal()
    output_device_changed = Signal(str)
    stream_state_changed = Signal()
    scheduled_status_changed = Signal(str)
    # Vystrelí, ked sa z playlistu vratia skladby spankovych zoznamov — UI si
    # na to vesia ulozenie stavu, aby na disku uz nikdy neostali.
    playlist_restored = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.playlist: list[Track] = []
        self.recent_tracks: list[Track] = []
        self.current_index = -1
        # Monotonic counter bumped only when the playlist *contents* change
        # (add / remove / move / clear / load). Lets remote clients know when
        # to refetch the playlist. current_index changes do NOT bump it.
        self._playlist_version = 0
        self.resume_position_ms = 0
        self.pending_seek_ms: int | None = None
        self.shutdown_when_playlist_ends = False
        self.sleep_when_playlist_ends = False
        self.scheduled_action = "none"
        self.scheduled_time = ""
        self._power_action_in_progress = False
        # Co pridali spankove tlacidla do playlistu: (ktore tlacidlo, skladby,
        # index skladby pred stlacenim). Pri ukonceni appky sa to odtial zase
        # vyhodi — pokial to `config.txt` klucom ..._NECHAT_V_PLAYLISTE nezakaze.
        #
        # Je to ZOZNAM a nie jedna polozka, lebo stlacit sa daju obe tlacidla za
        # sebou; kazdy zoznam je vtedy chvostom playlistu az dovtedy, kym za nim
        # nepribudne dalsi, takze sa musia odvijat v opacnom poradi.
        self._spanok_pending: list[tuple[str, list[str], int]] = []
        self._scheduled_timer = QTimer(self)
        self._scheduled_timer.setInterval(30_000)
        self._scheduled_timer.timeout.connect(self._on_scheduled_timer_tick)
        self._scheduled_target: datetime | None = None
        self._volume = 75
        self._api_url = ""
        self._snapshot_lock = threading.Lock()
        self._snapshot: dict = {}
        self._selected_output_device_id = ""
        self._needs_audio_reset = False
        self._last_error_kind = QMediaPlayer.Error.NoError
        self._pending_play = False
        self.total_tracks_played = 0
        self.total_listen_ms = 0
        # Listen-time / play-count accounting is driven by playback-position
        # deltas (see _on_position_changed): robust to gapless swaps, skips,
        # seeks and pipeline recreation, none of which a wall-clock "session"
        # handled reliably. _last_counted_position_ms is the baseline for the
        # next delta; _current_track_counted gates the once-per-track count.
        self._last_counted_position_ms = 0
        self._current_track_counted = False
        # Databaza prehrati po skladbach (music_player.statistika). Nastavuje
        # ju app.py; bez nej sa pocita len celkove cislo.
        self.statistika = None
        self._next_player: QMediaPlayer | None = None
        self._next_audio_output: QAudioOutput | None = None
        self._next_track_index: int = -1
        self._gapless_pending = False
        self._gapless_started = False
        self._current_rg_gain: float = 0.0
        self._next_rg_gain: float = 0.0
        # Path of the track we most recently requested to play.  Used to
        # validate that auto-advance uses the correct "next" track even when
        # the playlist contains duplicates of the same file.
        self._current_requested_path: str = ""
        # Default audio output device id observed the last time the pipeline
        # was created — used to detect Windows default-device changes when the
        # user is not overriding the output device.
        self._last_default_device_id: str = ""
        self.stream_manager: FfmpegStreamManager | None = None
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)

        self.player: QMediaPlayer
        self.audio_output: QAudioOutput
        self._create_audio_pipeline()
        self.set_volume(75)
        self._refresh_snapshot()

    def attach_stream_manager(self, stream_manager: FfmpegStreamManager) -> None:
        self.stream_manager = stream_manager
        self._refresh_snapshot()
        self.stream_state_changed.emit()

    def refresh_runtime_state(self) -> None:
        self._refresh_snapshot()
        self.stream_state_changed.emit()

    def load_state(self, state: AppState) -> None:
        self.playlist = list(state.playlist)
        self._bump_playlist_version()
        self.recent_tracks = list(state.recent_tracks)
        self.shutdown_when_playlist_ends = bool(state.shutdown_when_playlist_ends)
        self.sleep_when_playlist_ends = bool(state.sleep_when_playlist_ends)
        self.scheduled_action = state.scheduled_action if state.scheduled_action in ("none", "sleep", "shutdown") else "none"
        self.scheduled_time = state.scheduled_time if self._is_valid_time(state.scheduled_time) else ""
        self.total_tracks_played = state.total_tracks_played
        self.total_listen_ms = state.total_listen_ms
        self.set_volume(state.volume)
        if self.playlist:
            if state.current_index < 0 or state.current_index >= len(self.playlist):
                self.current_index = 0
                self.resume_position_ms = 0
            else:
                self.current_index = state.current_index
                self.resume_position_ms = state.position_ms
        else:
            self.current_index = -1
            self.resume_position_ms = 0
        self.set_output_device_id(state.output_device_id, recreate_audio_pipeline=True)
        self.playlist_changed.emit()
        self.recent_tracks_changed.emit()
        self.current_track_changed.emit(self.current_track())
        self.duration_changed.emit(int(self.player.duration()))
        self._refresh_snapshot()

    def build_state(
        self,
        *,
        start_with_windows: bool,
        window_width: int,
        window_height: int,
        playlist_window_width: int = 700,
        playlist_window_height: int = 500,
        playlist_window_visible: bool = True,
    ) -> AppState:
        position_ms = self.resume_position_ms
        if self.current_track() and Path(self.current_source_path()) == Path(self.current_track().path):
            position_ms = int(self.player.position())
        return AppState(
            playlist=list(self.playlist),
            recent_tracks=list(self.recent_tracks),
            current_index=self.current_index,
            position_ms=max(position_ms, 0),
            volume=self._volume,
            start_with_windows=bool(start_with_windows),
            shutdown_when_playlist_ends=bool(self.shutdown_when_playlist_ends),
            sleep_when_playlist_ends=bool(self.sleep_when_playlist_ends),
            scheduled_action=self.scheduled_action,
            scheduled_time=self.scheduled_time,
            output_device_id=self.current_output_device_id(),
            window_width=window_width,
            window_height=window_height,
            playlist_window_width=playlist_window_width,
            playlist_window_height=playlist_window_height,
            playlist_window_visible=playlist_window_visible,
            total_tracks_played=self.total_tracks_played,
            total_listen_ms=self._effective_listen_ms(),
        )

    def available_output_devices(self) -> list[tuple[str, str]]:
        devices: list[tuple[str, str]] = [("", "Predvolene Windows")]
        for device in QMediaDevices.audioOutputs():
            device_id = self._device_id(device)
            label = device.description()
            if device.isDefault():
                label = f"{label} (predvolene)"
            devices.append((device_id, label))
        return devices

    def current_output_device_id(self) -> str:
        if self._selected_output_device_id and self._resolve_output_device(self._selected_output_device_id) is not None:
            return self._selected_output_device_id
        return ""

    def current_output_device_description(self) -> str:
        selected_device = self._resolve_output_device(self._selected_output_device_id)
        if selected_device is not None:
            return selected_device.description()
        default_device = QMediaDevices.defaultAudioOutput()
        description = default_device.description().strip()
        return description or "Predvolene Windows"

    def set_output_device_id(self, device_id: str, *, recreate_audio_pipeline: bool = True) -> bool:
        normalized = str(device_id or "").strip()
        if normalized and self._resolve_output_device(normalized) is None:
            self.message_emitted.emit("Vybrane audio zariadenie uz nie je dostupne.")
            self._selected_output_device_id = ""
            self.output_device_changed.emit("")
            self._refresh_snapshot()
            return False

        was_playing = self.playback_state_name() == "playing"
        start_position_ms = int(self.player.position()) if self.current_track() else self.resume_position_ms
        self._selected_output_device_id = normalized

        if recreate_audio_pipeline:
            self.reset_audio_pipeline(
                reload_current=True,
                autoplay=was_playing,
                preserve_position=True,
                start_position_ms=start_position_ms,
            )
        else:
            self._apply_output_device_to_current_audio_output()
            self._refresh_snapshot()

        self.output_device_changed.emit(self.current_output_device_id())
        return True

    def retry_playback(self) -> None:
        if not self.playlist:
            self.message_emitted.emit("Playlist je prazdny.")
            return
        target_index = self.current_index if 0 <= self.current_index < len(self.playlist) else 0
        start_position_ms = int(self.player.position()) if self.current_track() else self.resume_position_ms
        self.reset_audio_pipeline(reload_current=False, autoplay=False, preserve_position=False)
        self.play_track_at(target_index, start_position_ms=start_position_ms)

    def add_paths(
        self,
        paths: list[str],
        *,
        play_on_first_add: bool = False,
        insert_at: int | None = None,
    ) -> tuple[int, int | None]:
        added = 0
        first_added_index: int | None = None
        playlist_was_empty = not self.playlist
        insert_pos = insert_at if insert_at is not None else len(self.playlist)

        for path in collect_audio_paths(paths):
            self.playlist.insert(insert_pos, Track.from_path(path))
            if first_added_index is None:
                first_added_index = insert_pos
            insert_pos += 1
            added += 1

        if added and self.current_index >= 0 and first_added_index is not None and first_added_index <= self.current_index:
            self.current_index += added
        if added and (self.current_index < 0 or self.current_index >= len(self.playlist)):
            self.current_index = first_added_index if first_added_index is not None else 0
            self.resume_position_ms = 0

        if added:
            self._bump_playlist_version()
            self.playlist_changed.emit()
            self.current_track_changed.emit(self.current_track())
            self._refresh_snapshot()
            if play_on_first_add and playlist_was_empty and first_added_index is not None:
                self.play_track_at(first_added_index)

        return added, first_added_index

    def move_indices(self, indices: list[int], target: int) -> list[int]:
        """Move playlist items at *indices* so that they end up at *target*.

        Returns the new row indices of the moved items (for re-selection).
        """
        sorted_src = sorted(set(i for i in indices if 0 <= i < len(self.playlist)))
        if not sorted_src:
            return []

        # Pull out the moved tracks and figure out where current_index lands.
        moved = [self.playlist[i] for i in sorted_src]
        # Track the *exact* currently-playing Track object, not its path.  The
        # playlist may contain duplicates of the same file; matching by path
        # would snap current_index back to the first occurrence and replay the
        # rest of the playlist (and "shutdown when playlist ends" would never
        # fire because the true end is never reached).  Reordering only shuffles
        # existing Track instances, so object identity survives the rebuild.
        current_track_obj = self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None

        remaining = [t for i, t in enumerate(self.playlist) if i not in set(sorted_src)]

        # Adjust target for removed items above it.
        adjusted_target = target - sum(1 for i in sorted_src if i < target)
        adjusted_target = max(0, min(adjusted_target, len(remaining)))

        new_playlist = remaining[:adjusted_target] + moved + remaining[adjusted_target:]
        self.playlist = new_playlist

        # Restore current_index to the track that was playing (by identity).
        if current_track_obj is not None:
            for i, t in enumerate(self.playlist):
                if t is current_track_obj:
                    self.current_index = i
                    break

        new_selection = list(range(adjusted_target, adjusted_target + len(moved)))
        self._bump_playlist_version()
        self.playlist_changed.emit()
        self._refresh_snapshot()
        return new_selection

    def remove_indices(self, indices: list[int]) -> None:
        if not indices:
            return
        sorted_indices = sorted(set(index for index in indices if 0 <= index < len(self.playlist)))
        if not sorted_indices:
            return

        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        removed_current = self.current_index in sorted_indices

        for index in reversed(sorted_indices):
            del self.playlist[index]

        if not self.playlist:
            self.player.stop()
            self._stop_streaming()
            self.current_index = -1
            self.resume_position_ms = 0
        elif removed_current:
            self.player.stop()
            self._stop_streaming()
            self.current_index = min(sorted_indices[0], len(self.playlist) - 1)
            self.resume_position_ms = 0
            if was_playing:
                self.play_track_at(self.current_index)
        else:
            shift = sum(1 for index in sorted_indices if index < self.current_index)
            self.current_index -= shift

        self._bump_playlist_version()
        self.playlist_changed.emit()
        self.current_track_changed.emit(self.current_track())
        self._refresh_snapshot()

    def clear_playlist(self) -> None:
        self.player.stop()
        self._stop_streaming()
        self.playlist = []
        self.current_index = -1
        self.resume_position_ms = 0
        self._bump_playlist_version()
        self.playlist_changed.emit()
        self.current_track_changed.emit(None)
        self.duration_changed.emit(0)
        self._refresh_snapshot()

    def play_or_resume(self) -> None:
        if not self.playlist:
            self.message_emitted.emit("Playlist je prazdny.")
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        if self._needs_audio_reset:
            self.retry_playback()
            return
        target_index = self.current_index if self.current_index >= 0 else 0
        current_track = self.current_track()
        if current_track and Path(self.current_source_path()) == Path(current_track.path):
            self.player.play()
            self._start_streaming(current_track.path, self.resume_position_ms)
            return
        self.play_track_at(target_index, start_position_ms=self.resume_position_ms)

    def play_track_at(self, index: int, start_position_ms: int = 0) -> None:
        if not (0 <= index < len(self.playlist)):
            return
        self._dispose_next_player()
        track = self.playlist[index]
        self.current_index = index
        self._current_requested_path = track.path
        self.resume_position_ms = max(start_position_ms, 0)
        self.pending_seek_ms = self.resume_position_ms if self.resume_position_ms > 0 else None
        self._needs_audio_reset = False
        self._last_error_kind = QMediaPlayer.Error.NoError
        self.player.stop()
        self._stop_streaming()
        # Always clear the source before setting it — this forces a full reload
        # even when re-selecting the same file (duplicates in the playlist) and
        # guarantees mediaStatusChanged(LoadedMedia) fires for the new load so
        # _pending_play is honored.
        self.player.setSource(QUrl())
        self._current_rg_gain = self._read_replaygain(track.path)
        self._apply_volume()
        self._pending_play = True
        self.player.setSource(QUrl.fromLocalFile(track.path))
        self._reset_track_accounting()
        self._remember_track(track)
        self.current_track_changed.emit(track)
        self.recent_tracks_changed.emit()
        self._refresh_snapshot()

    def navigate_to_track(self, index: int) -> None:
        """Load track without auto-playing (preserves stopped/paused state)."""
        if not (0 <= index < len(self.playlist)):
            return
        self._dispose_next_player()
        track = self.playlist[index]
        self.current_index = index
        self._current_requested_path = track.path
        self.resume_position_ms = 0
        self.pending_seek_ms = None
        self._needs_audio_reset = False
        self._last_error_kind = QMediaPlayer.Error.NoError
        self.player.stop()
        self._stop_streaming()
        self._pending_play = False
        self.player.setSource(QUrl())
        self.player.setSource(QUrl.fromLocalFile(track.path))
        self._reset_track_accounting()
        self._remember_track(track)
        self.current_track_changed.emit(track)
        self.recent_tracks_changed.emit()
        self._refresh_snapshot()

    def pause(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self._stop_streaming()

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play_or_resume()

    def stop(self) -> None:
        self.player.stop()
        self._stop_streaming()
        self.resume_position_ms = 0
        self._refresh_snapshot()

    def seek(self, position_ms: int) -> None:
        if self.current_track() is None:
            return
        target_position = max(int(position_ms), 0)
        duration_ms = int(self.player.duration())
        if duration_ms > 0:
            target_position = min(target_position, duration_ms)
        self.pending_seek_ms = None
        self.resume_position_ms = target_position
        self.player.setPosition(target_position)
        if self.playback_state_name() == "playing":
            current = self.current_track()
            if current is not None:
                self._start_streaming(current.path, target_position)
        self.position_changed.emit(target_position)
        self._refresh_snapshot()

    def next_track(self) -> None:
        if self.current_index + 1 < len(self.playlist):
            if self.playback_state_name() == "playing":
                self.play_track_at(self.current_index + 1)
            else:
                self.navigate_to_track(self.current_index + 1)
        else:
            self.player.stop()
            self._stop_streaming()
            self.resume_position_ms = 0
            self._refresh_snapshot()

    def previous_track(self) -> None:
        if self.player.position() > 3000:
            self.seek(0)
            return
        was_playing = self.playback_state_name() == "playing"
        if self.current_index > 0:
            if was_playing:
                self.play_track_at(self.current_index - 1)
            else:
                self.navigate_to_track(self.current_index - 1)
        elif self.current_index == 0:
            self.seek(0)

    def jump_to_sleep_tail(self) -> int:
        """Skok na tretiu skladbu od konca — zaloha pre "Spanok" bez zoznamu.

        Do 1. 9. 2026 to bolo jedine spravanie tlacidla "Spanok". Odvtedy ma
        tlacidlo vlastny zoznam (`spanok.m3u`) a sem sa pride uz len vtedy, ked
        je ten zoznam prazdny — nech tlacidlo nezostane bez funkcie, kym si ho
        clovek nenaplni.

        Zachova stav prehravania: ak sa hra, cielova skladba sa rovno pusti,
        inak sa iba nacita. Vracia index cielovej skladby (-1 ak sa neskocilo).
        """
        if not self.playlist:
            self.message_emitted.emit("Playlist je prazdny.")
            return -1
        target = max(len(self.playlist) - _SLEEP_TAIL_TRACKS, 0)
        remaining = len(self.playlist) - target
        if target == self.current_index:
            # Uz sme presne tam — neresetuj prave hrajucu skladbu.
            self.message_emitted.emit(
                f"Spánok: do konca playlistu zostávajú už len {remaining} skladby."
            )
            return target
        if self.playback_state_name() == "playing":
            self.play_track_at(target)
        else:
            self.navigate_to_track(target)
        self.message_emitted.emit(
            f"Spánok: skok na skladbu {target + 1}/{len(self.playlist)} "
            f"(zostávajú {remaining})." + self._power_action_hint()
        )
        return target

    def _power_action_hint(self) -> str:
        """Doveta do hlasky: co sa stane po dohrati playlistu."""
        if self.shutdown_when_playlist_ends:
            return " Po dohratí sa PC vypne."
        if self.sleep_when_playlist_ends:
            return " Po dohratí sa PC uspí."
        return " Pozor: vypnutie ani uspanie po skončení nie je zapnuté."

    def start_spanok(self, ktory: str) -> tuple[int, list[str]]:
        """Spolocna obsluha tlacidiel "Spanok" a "Spanok 2".

        Skladby zo zoznamu sa pridaju na koniec playlistu a prehravanie skoci na
        prvu z nich. Po ich dohrati teda playlist skonci a plati nastavene
        vypnutie/uspanie po skonceni.

        Ked playlist UZ konci presne tymito skladbami, nepridava sa NIC — len sa
        na ne skoci a playlist ostane, aky bol. Bez tejto kontroly by kazde
        dalsie stlacenie lepilo ten isty chvost dokola; s nou sa da tlacidlo
        stlacit hoci kazdy vecer a playlist z toho nenarastie.

        Vracia (index prvej skladby zoznamu, chybajuce riadky zoznamu). Index je
        -1, ak sa nepustilo nic.
        """
        from music_player import spanky

        meno = spanky.nazov(ktory)
        zoznam = spanky.load(ktory)
        tracks, missing = zoznam.tracks, zoznam.missing

        if not tracks:
            if missing:
                self.message_emitted.emit(
                    f"{meno}: ani jedna z {len(missing)} skladieb zoznamu sa nenašla "
                    f"na disku ({spanky.playlist_path(ktory)})."
                )
                return -1, missing
            if ktory == spanky.SPANOK:
                return self.jump_to_sleep_tail(), []
            self.message_emitted.emit(
                f"{meno}: zoznam skladieb ešte nie je zadefinovaný "
                f"({spanky.playlist_path(ktory)})."
            )
            return -1, missing

        target = self._spanok_tail_index(tracks)
        if target < 0:
            previous_index = self.current_index
            added, first_index = self.add_paths(tracks)
            if not added or first_index is None:
                self.message_emitted.emit(
                    f"{meno}: skladby zo zoznamu sa nepodarilo pridať do playlistu."
                )
                return -1, missing
            target = first_index
            pridane = True
        else:
            # Zoznam uz na konci playlistu je (druhe stlacenie, alebo zvysok
            # z minula) — vratit sa teda mame na skladbu tesne pred nim.
            previous_index = max(target - 1, 0)
            pridane = False

        if spanky.nechat_v_playliste(ktory):
            self._zabudni_spanok(ktory)
        else:
            self._zapamataj_spanok(ktory, tracks, previous_index)

        self.play_track_at(target)
        count = len(self.playlist) - target
        warn = f" Chýbajúce skladby zoznamu: {len(missing)}." if missing else ""
        if not pridane:
            kde = " Playlist sa nemenil, skladby v ňom už boli."
        elif spanky.nechat_v_playliste(ktory):
            kde = " Skladby ostanú v playliste."
        else:
            kde = " Po ukončení prehrávača sa z playlistu zase vyhodia."
        self.message_emitted.emit(
            f"{meno}: hrá {count} skladieb, štart na "
            f"{target + 1}/{len(self.playlist)}." + warn + kde + self._power_action_hint()
        )
        return target, missing

    def start_sleep2(self) -> tuple[int, list[str]]:
        """Tlacidlo "Spanok 2" — zachovane meno pre API akciu `sleep2` a UI."""
        from music_player import spanky

        return self.start_spanok(spanky.SPANOK2)

    def _zapamataj_spanok(self, ktory: str, tracks: list[str], previous_index: int) -> None:
        """Poznaci si, co tlacidlo do playlistu pridalo.

        Prve stlacenie si stav zapamata, dalsie ho uz neprepisu — inak by sa po
        druhom stlaceni vracalo na miesto, ktore uz samo bolo vysledkom prveho.
        """
        if any(polozka[0] == ktory for polozka in self._spanok_pending):
            return
        self._spanok_pending.append((ktory, list(tracks), previous_index))

    def _zabudni_spanok(self, ktory: str) -> None:
        """Skladby tohto tlacidla maju v playliste ostat — netreba ich vracat."""
        self._spanok_pending = [p for p in self._spanok_pending if p[0] != ktory]

    def restore_spanok_lists(self) -> None:
        """Vyhodi z playlistu skladby, ktore tam pridali spankove tlacidla.

        Vola sa pri ukonceni prehravaca, este PRED ulozenim stavu — inak by sa
        skladby ulozili do `state.json` a na druhy den by v playliste zase boli.

        Odvija sa v opacnom poradi, nez sa pridavali. Ked chvost uz nesedi
        (playlist sa medzitym rucne zmenil), necha sa tak: cudzie zmeny sa
        nemazu. Nic sa tym nerozbije — pri dalsom stlaceni tlacidla sa taky
        zvysok rozpozna ako uz pritomny a neprida sa druhy raz.
        """
        if not self._spanok_pending:
            return
        zmenene = False
        for _ktory, tracks, return_index in reversed(self._spanok_pending):
            start = self._spanok_tail_index(tracks)
            if start < 0:
                continue
            del self.playlist[start:]
            self.current_index = (
                min(return_index, len(self.playlist) - 1) if self.playlist else -1
            )
            zmenene = True
        self._spanok_pending.clear()
        if not zmenene:
            return
        self.resume_position_ms = 0
        self.pending_seek_ms = None
        self._dispose_next_player()
        self._bump_playlist_version()
        self.playlist_changed.emit()
        self.current_track_changed.emit(self.current_track())
        self._refresh_snapshot()
        self.playlist_restored.emit()

    def _spanok_tail_index(self, tracks: list[str]) -> int:
        """Index, od ktoreho playlist konci presne skladbami zo zoznamu.

        Vracia -1, ak tam zoznam este nie je — vtedy sa musi pridat. Porovnava sa
        LEN chvost: to je cela podstata poistky proti opakovanemu pridavaniu.
        """
        if not tracks or len(tracks) > len(self.playlist):
            return -1
        start = len(self.playlist) - len(tracks)
        for offset, path in enumerate(tracks):
            if self.playlist[start + offset].path.lower() != path.lower():
                return -1
        return start

    def play_history_item(self, path: str) -> None:
        normalized_path = str(Path(path).expanduser().resolve())
        for index, track in enumerate(self.playlist):
            if track.path.lower() == normalized_path.lower():
                self.play_track_at(index)
                return
        self.add_paths([normalized_path])
        for index, track in enumerate(self.playlist):
            if track.path.lower() == normalized_path.lower():
                self.play_track_at(index)
                return

    def set_volume(self, value: int) -> None:
        volume = max(0, min(100, int(value)))
        self._volume = volume
        self._apply_volume()
        self.volume_changed.emit(volume)
        self._refresh_snapshot()

    def _apply_volume(self) -> None:
        """Apply user volume with ReplayGain adjustment."""
        base = self._volume / 100.0
        gain = self._current_rg_gain
        if gain != 0.0:
            # Convert dB gain to linear scale, clamp to avoid clipping
            import math
            factor = min(math.pow(10, gain / 20.0), 2.0)
            base = min(base * factor, 1.0)
        self.audio_output.setVolume(max(base, 0.0))

    def _read_replaygain(self, path: str) -> float:
        """Read ReplayGain tag from file. Returns gain in dB (0.0 if none)."""
        try:
            from mutagen import File as MutagenFile
            f = MutagenFile(path, easy=True)
            if f is None:
                return 0.0
            # Try track gain first, then album gain
            for key in ("replaygain_track_gain", "replaygain_album_gain"):
                val = f.get(key)
                if val:
                    s = str(val[0] if isinstance(val, list) else val)
                    s = s.replace("dB", "").replace("db", "").strip()
                    return float(s)
        except Exception:
            pass
        return 0.0

    def set_api_url(self, api_url: str) -> None:
        self._api_url = api_url
        self._refresh_snapshot()

    def current_track(self) -> Track | None:
        if 0 <= self.current_index < len(self.playlist):
            return self.playlist[self.current_index]
        return None

    def current_source_path(self) -> str:
        source = self.player.source()
        if source.isEmpty():
            return ""
        return source.toLocalFile()

    def playback_state_name(self) -> str:
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            return "playing"
        if state == QMediaPlayer.PlaybackState.PausedState:
            return "paused"
        return "stopped"

    def snapshot(self) -> dict:
        with self._snapshot_lock:
            return dict(self._snapshot)

    def _bump_playlist_version(self) -> None:
        self._playlist_version += 1

    def playlist_payload(self) -> dict:
        """Full playlist for remote clients (served at GET /api/playlist)."""
        return {
            "version": self._playlist_version,
            "currentIndex": self.current_index,
            "items": [
                {
                    "index": i,
                    "title": track.title,
                    "artist": track.artist,
                    "durationMs": int(track.duration_ms),
                }
                for i, track in enumerate(self.playlist)
            ],
        }

    def handle_remote_command(self, action: str, params: dict) -> None:
        """Dispatch a remote-control command onto player methods.

        Runs on the Qt main thread (invoked via a queued-connection signal from
        the HTTP server thread) so QMediaPlayer is only ever touched here.
        Unknown actions and bad params are silently ignored.
        """
        params = params or {}
        try:
            if action == "playpause":
                self.toggle_playback()
            elif action == "stop":
                self.stop()
            elif action == "next":
                self.next_track()
            elif action == "prev":
                self.previous_track()
            elif action == "seek":
                self.seek(int(params.get("positionMs", 0)))
            elif action == "playIndex":
                self.play_track_at(int(params.get("index", -1)))
            elif action == "setVolume":
                self.set_volume(int(params.get("value", self._volume)))
            elif action == "spanok":
                # Tlacidlo "Spanok" z widgetu. Uspanie samotne nerobi: o to sa
                # postara "Vypnut/Spat po skonceni", presne ako ked sa tlacidlo
                # stlaci tu na PC.
                from music_player import spanky
                self.start_spanok(spanky.SPANOK)
            elif action == "sleep2":
                self.start_sleep2()
            elif action == "shutdown":
                if not self._power_action_in_progress:
                    self._power_action_in_progress = True
                    shutdown_windows()
            elif action == "sleep":
                if not self._power_action_in_progress:
                    self._power_action_in_progress = True
                    sleep_windows()
                    self._power_action_in_progress = False
        except (ValueError, TypeError, KeyError):
            pass

    def reset_audio_pipeline(
        self,
        *,
        reload_current: bool,
        autoplay: bool,
        preserve_position: bool,
        start_position_ms: int | None = None,
    ) -> None:
        current = self.current_track()
        if start_position_ms is None:
            if preserve_position and current is not None:
                start_position_ms = int(self.player.position())
            elif preserve_position:
                start_position_ms = self.resume_position_ms
            else:
                start_position_ms = 0

        self._create_audio_pipeline()
        self.set_volume(self._volume)
        self._needs_audio_reset = False
        self._last_error_kind = QMediaPlayer.Error.NoError
        self.resume_position_ms = max(int(start_position_ms or 0), 0)
        # Same track, fresh player: re-baseline the position delta so the
        # reload jump is not counted, but keep the per-track count gate.
        self._last_counted_position_ms = self.resume_position_ms

        if current is not None and reload_current:
            self.pending_seek_ms = self.resume_position_ms if self.resume_position_ms > 0 else None
            self._pending_play = autoplay
            self.player.setSource(QUrl.fromLocalFile(current.path))
            self.current_track_changed.emit(current)
        else:
            self._pending_play = False
            self.pending_seek_ms = None

        self.duration_changed.emit(int(self.player.duration()))
        self._refresh_snapshot()

    def _remember_track(self, track: Track) -> None:
        self.recent_tracks = [item for item in self.recent_tracks if item.path.lower() != track.path.lower()]
        self.recent_tracks.insert(0, track)
        self.recent_tracks = self.recent_tracks[:20]

    def _create_audio_pipeline(self) -> None:
        old_player = getattr(self, "player", None)
        old_audio_output = getattr(self, "audio_output", None)

        if old_player is not None:
            try:
                old_player.stop()
            except RuntimeError:
                pass

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self._apply_output_device_to_current_audio_output()
        self.player.setAudioOutput(self.audio_output)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.errorOccurred.connect(self._on_error_occurred)

        if old_player is not None:
            old_player.deleteLater()
        if old_audio_output is not None:
            old_audio_output.deleteLater()

    def _apply_output_device_to_current_audio_output(self) -> None:
        selected_device = self._resolve_output_device(self._selected_output_device_id)
        if selected_device is not None:
            self.audio_output.setDevice(selected_device)
        else:
            # "Windows default" — explicitly pin to the *current* default device
            # so subsequent OS default changes can be detected (by comparing
            # against _last_default_device_id) and the pipeline rebuilt.
            default_device = QMediaDevices.defaultAudioOutput()
            try:
                self.audio_output.setDevice(default_device)
            except Exception:
                pass
        self._last_default_device_id = self._current_default_device_id()

    def _resolve_output_device(self, device_id: str):
        normalized = str(device_id or "").strip()
        if not normalized:
            return None
        for device in QMediaDevices.audioOutputs():
            if self._device_id(device) == normalized:
                return device
        return None

    def _device_id(self, device) -> str:
        return bytes(device.id()).hex()

    def _start_streaming(self, track_path: str, position_ms: int) -> None:
        if self.stream_manager is None:
            return
        started = self.stream_manager.start_track(track_path, position_ms)
        if not started:
            stream_status = self.stream_manager.status()
            if stream_status.last_error:
                self.message_emitted.emit(stream_status.last_error)
        self.stream_state_changed.emit()

    def _stop_streaming(self) -> None:
        if self.stream_manager is None:
            return
        self.stream_manager.stop()
        self.stream_state_changed.emit()

    def _stream_status_payload(self) -> dict:
        if self.stream_manager is None:
            return {
                "available": False,
                "active": False,
                "url": None,
                "codec": None,
                "last_error": "",
            }
        status = self.stream_manager.status()
        return {
            "available": status.available,
            "active": status.active,
            "url": status.url,
            "codec": status.codec,
            "last_error": status.last_error,
        }

    def _on_audio_outputs_changed(self) -> None:
        was_playing = self.playback_state_name() == "playing"
        pipeline_rebuilt = False
        if self._selected_output_device_id and self._resolve_output_device(self._selected_output_device_id) is None:
            self._selected_output_device_id = ""
            self.message_emitted.emit("Povodne audio zariadenie zmizlo. Pouziva sa predvolene Windows zariadenie.")
            self.reset_audio_pipeline(
                reload_current=True, autoplay=was_playing, preserve_position=True
            )
            pipeline_rebuilt = True
        elif not self._selected_output_device_id:
            # User is on "Windows default".  QAudioOutput latches the default
            # device at creation time and does NOT follow live default changes
            # (e.g. user plugs in headphones / changes default in Windows
            # Sound settings).  Detect the change and rebuild the pipeline so
            # playback continues on the new default device.
            current_default_id = self._current_default_device_id()
            if current_default_id and current_default_id != self._last_default_device_id:
                self._last_default_device_id = current_default_id
                self.reset_audio_pipeline(
                    reload_current=True, autoplay=was_playing, preserve_position=True
                )
                pipeline_rebuilt = True
        if not pipeline_rebuilt:
            # Keep last-seen default in sync even if nothing needed to rebuild.
            self._last_default_device_id = self._current_default_device_id()
        self.audio_outputs_changed.emit()
        self.output_device_changed.emit(self.current_output_device_id())
        self._refresh_snapshot()

    def _current_default_device_id(self) -> str:
        default_device = QMediaDevices.defaultAudioOutput()
        try:
            raw = bytes(default_device.id())
        except Exception:
            return ""
        return raw.hex()

    # ── gapless playback ────────────────────────────────────────────────────────
    def _preload_next_track(self) -> None:
        next_idx = self.current_index + 1
        if next_idx >= len(self.playlist):
            return
        if self._next_player is not None and self._next_track_index == next_idx:
            return  # already preloaded
        self._dispose_next_player()
        track = self.playlist[next_idx]
        self._next_audio_output = QAudioOutput(self)
        selected_device = self._resolve_output_device(self._selected_output_device_id)
        if selected_device is not None:
            self._next_audio_output.setDevice(selected_device)
        rg = self._read_replaygain(track.path)
        self._next_rg_gain = rg
        self._next_audio_output.setVolume(self._volume / 100.0)
        self._next_player = QMediaPlayer(self)
        self._next_player.setAudioOutput(self._next_audio_output)
        self._next_player.mediaStatusChanged.connect(self._on_next_media_status)
        self._next_player.setSource(QUrl.fromLocalFile(track.path))
        self._next_track_index = next_idx

    def _on_next_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._gapless_pending = True

    def _switch_to_next_player(self) -> None:
        if self._next_player is None:
            return
        self._gapless_pending = False
        self._gapless_started = False
        old_player = self.player
        old_output = self.audio_output
        old_player.stop()
        # Swap players — next player is already playing
        self.player = self._next_player
        self.audio_output = self._next_audio_output
        self._next_player = None
        self._next_audio_output = None
        # Disconnect old next-media-status, connect main signals
        try:
            self.player.mediaStatusChanged.disconnect(self._on_next_media_status)
        except RuntimeError:
            pass
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.errorOccurred.connect(self._on_error_occurred)
        # Update state
        self.current_index = self._next_track_index
        self._next_track_index = -1
        self._current_rg_gain = getattr(self, "_next_rg_gain", 0.0)
        self._apply_volume()
        self.resume_position_ms = 0
        self.pending_seek_ms = None
        self._pending_play = False
        # New track now owns the position stream — start its accounting fresh.
        self._reset_track_accounting()
        # Next player is already playing — just update UI
        if not self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()
        current = self.current_track()
        if current is not None:
            self._start_streaming(current.path, 0)
            self._remember_track(current)
        self.current_track_changed.emit(current)
        self.recent_tracks_changed.emit()
        self.duration_changed.emit(int(self.player.duration()))
        self._refresh_snapshot()
        old_player.deleteLater()
        old_output.deleteLater()

    def _dispose_next_player(self) -> None:
        if self._next_player is not None:
            self._next_player.stop()
            self._next_player.deleteLater()
            self._next_player = None
        if self._next_audio_output is not None:
            self._next_audio_output.deleteLater()
            self._next_audio_output = None
        self._next_track_index = -1
        self._gapless_pending = False
        self._gapless_started = False

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            if self.pending_seek_ms is not None:
                self.player.setPosition(self.pending_seek_ms)
                self.pending_seek_ms = None
            if self._pending_play:
                self._pending_play = False
                self.player.play()
                current = self.current_track()
                if current is not None:
                    self._start_streaming(current.path, self.resume_position_ms)
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._pending_play = False
            current = self.current_track()
            if current is not None:
                self.message_emitted.emit(
                    f"Nepodarilo sa nacitat {Path(current.path).name}. Skontroluj subor alebo format."
                )
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._handle_end_of_track()
        self._refresh_snapshot()

    # ── scheduled power action ─────────────────────────────────────────────────

    def start_scheduled_timer(self) -> None:
        if self.scheduled_action != "none" and self._is_valid_time(self.scheduled_time):
            self._scheduled_target = self._next_occurrence(self.scheduled_time)
            self._scheduled_timer.start()
            self._emit_scheduled_status()
        else:
            self.scheduled_action = "none"
            self.scheduled_time = ""

    def set_scheduled_action(self, action: str) -> None:
        self.scheduled_action = action
        self._scheduled_timer.stop()
        self._scheduled_target = None
        if action != "none" and self._is_valid_time(self.scheduled_time):
            self._scheduled_target = self._next_occurrence(self.scheduled_time)
            self._scheduled_timer.start()
        self._emit_scheduled_status()

    def set_scheduled_time(self, hhmm: str) -> None:
        self.scheduled_time = hhmm
        self._scheduled_timer.stop()
        self._scheduled_target = None
        if self.scheduled_action != "none" and self._is_valid_time(hhmm):
            self._scheduled_target = self._next_occurrence(hhmm)
            self._scheduled_timer.start()
        self._emit_scheduled_status()

    def _on_scheduled_timer_tick(self) -> None:
        target = self._scheduled_target
        if target is None:
            self._cancel_scheduled_action()
            return
        now = datetime.now()
        if now < target:
            return
        if (now - target).total_seconds() <= _SCHEDULED_GRACE_S:
            self._execute_scheduled_action()
        else:
            self._cancel_scheduled_action()

    def _execute_scheduled_action(self) -> None:
        if self._power_action_in_progress:
            return
        self._power_action_in_progress = True
        action = self.scheduled_action
        self._cancel_scheduled_action()
        if action == "sleep":
            self.message_emitted.emit("Naplánované uspanie sa vykonáva...")
            sleep_windows()
            self._power_action_in_progress = False
        elif action == "shutdown":
            self.message_emitted.emit("Naplánované vypnutie sa vykonáva...")
            shutdown_windows()

    def _cancel_scheduled_action(self) -> None:
        self.scheduled_action = "none"
        self.scheduled_time = ""
        self._scheduled_target = None
        self._scheduled_timer.stop()
        self._emit_scheduled_status()

    def _emit_scheduled_status(self) -> None:
        if self.scheduled_action != "none" and self._is_valid_time(self.scheduled_time):
            verb = "Uspanie" if self.scheduled_action == "sleep" else "Vypnutie"
            target = self._scheduled_target
            day = " (zajtra)" if target is not None and target.date() != datetime.now().date() else ""
            self.scheduled_status_changed.emit(
                f"{verb} naplánované o {self.scheduled_time}{day} — formát hodiny:minúty"
            )
        else:
            self.scheduled_status_changed.emit("")

    @staticmethod
    def _is_valid_time(hhmm: str) -> bool:
        try:
            parts = hhmm.split(":")
            if len(parts) != 2:
                return False
            h, m = int(parts[0]), int(parts[1])
            return 0 <= h <= 23 and 0 <= m <= 59
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _next_occurrence(hhmm: str) -> datetime:
        """Nearest future moment with the given wall-clock time — today if it
        has not passed yet, otherwise tomorrow."""
        h, m = (int(p) for p in hhmm.split(":"))
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    def _handle_end_of_track(self) -> None:
        self.resume_position_ms = 0
        if self.current_index + 1 < len(self.playlist):
            # Next player already playing (started 300ms before end) — just swap,
            # but only if the preloaded track is the one that *follows* the
            # user's currently-requested track.  Without this check, a stale
            # gapless preload can cause a jump to the track after the wrong
            # occurrence when duplicates exist in the playlist.
            preloaded_next_path = (
                self.playlist[self._next_track_index].path
                if 0 <= self._next_track_index < len(self.playlist)
                else ""
            )
            expected_next_path = self.playlist[self.current_index + 1].path
            if (
                self._gapless_started
                and self._next_track_index == self.current_index + 1
                and preloaded_next_path == expected_next_path
            ):
                self._switch_to_next_player()
                return
            self.play_track_at(self.current_index + 1)
            return
        self.player.stop()
        self._stop_streaming()
        if self._power_action_in_progress:
            return
        # Skladby spankovych zoznamov sa tu UZ NEVRACAJU. Do 1. 9. 2026 sa
        # playlist cistil prave tu, po dohrati poslednej skladby — lenze to je
        # ta ista chvila, v ktorej sa PC uspava alebo vypina, takze sa navrat
        # casto ani nestihol ulozit. Odteraz sa cisti az pri ukonceni appky
        # (`restore_spanok_lists`), kde na to je pokoj.
        had_tracks = bool(self.playlist)
        if self.shutdown_when_playlist_ends and had_tracks:
            self._power_action_in_progress = True
            self.message_emitted.emit("Playlist dohral. Windows sa vypina.")
            shutdown_windows()
        elif self.sleep_when_playlist_ends and had_tracks:
            self._power_action_in_progress = True
            self.message_emitted.emit("Playlist dohral. Windows prechádza do režimu spánku.")
            sleep_windows()
            self._power_action_in_progress = False

    def _reset_track_accounting(self) -> None:
        """Reset the per-track listen baseline + play-count gate.

        Call whenever a different track starts (play / navigate / gapless swap /
        pipeline reload) so the next position delta is not measured across the
        track boundary and the new track can be counted once.
        """
        self._last_counted_position_ms = max(int(self.player.position()), 0)
        self._current_track_counted = False

    def _effective_listen_ms(self) -> int:
        """Total listen time. Accounting is committed live in
        _on_position_changed, so there is no open session to add."""
        return self.total_listen_ms

    def _on_playback_state_changed(self, _state: QMediaPlayer.PlaybackState) -> None:
        self.playback_state_changed.emit(self.playback_state_name())
        self._refresh_snapshot()

    def _on_position_changed(self, position: int) -> None:
        position = max(position, 0)
        # Listen-time + play-count accounting from position deltas. Counting
        # only while actually playing means stalls/buffering are not counted;
        # the delta cap rejects seeks and track-boundary jumps.
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            delta = position - self._last_counted_position_ms
            if 0 < delta <= _MAX_LISTEN_DELTA_MS:
                self.total_listen_ms += delta
            if not self._current_track_counted:
                duration = int(self.player.duration())
                threshold = min(30_000, int(duration * 0.3)) if duration > 0 else 30_000
                if position >= threshold:
                    self.total_tracks_played += 1
                    self._current_track_counted = True
                    track = self.current_track()
                    if self.statistika is not None and track is not None:
                        self.statistika.zaznamenaj(track)
        self._last_counted_position_ms = position

        self.resume_position_ms = position
        self.position_changed.emit(position)
        # Gapless: preload next track 5s before end, start it 300ms before end
        duration = int(self.player.duration())
        if duration > 0 and position > 0:
            remaining = duration - position
            if remaining < 5000:
                self._preload_next_track()
            if (
                remaining < 300
                and self._gapless_pending
                and not self._gapless_started
                # A late mediaStatus event can set _gapless_pending after the
                # preloaded player was already disposed (rapid track switching).
                and self._next_player is not None
            ):
                self._gapless_started = True
                self._next_player.play()
        self._refresh_snapshot()

    def _on_duration_changed(self, duration: int) -> None:
        self.duration_changed.emit(max(int(duration), 0))
        self._refresh_snapshot()

    def _on_error_occurred(self, error: QMediaPlayer.Error, *_args) -> None:
        self._pending_play = False
        self._needs_audio_reset = True
        self._last_error_kind = error
        base_error_text = self.player.errorString().strip() or "Prehravanie zlyhalo."
        current = self.current_track()
        prefix = f"{Path(current.path).name}: " if current is not None else ""

        if error == QMediaPlayer.Error.AccessDeniedError:
            error_text = (
                f"{prefix}Audio vystup je momentalne obsadeny inou aplikaciou. "
                "Skus zavriet tu aplikaciu, zmenit vystup alebo stlacit 'Obnovit audio'."
            )
        elif error == QMediaPlayer.Error.ResourceError:
            error_text = (
                f"{prefix}{base_error_text} "
                "Ak bolo zariadenie predtym blokovane, skus 'Obnovit audio'."
            )
        else:
            error_text = f"{prefix}{base_error_text}"

        self.message_emitted.emit(error_text)
        self._refresh_snapshot()

    def _refresh_snapshot(self) -> None:
        current = self.current_track()
        stream_payload = self._stream_status_payload()
        payload = {
            "title": current.title if current else "",
            "artist": current.artist if current else "",
            "path": current.path if current else "",
            "durationMs": int(self.player.duration()),
            "positionMs": int(self.player.position()),
            "state": self.playback_state_name(),
            "playlistCount": len(self.playlist),
            "currentIndex": self.current_index,
            "playlistVersion": self._playlist_version,
            "volume": self._volume,
            "history": [track.display_text for track in self.recent_tracks],
            "apiUrl": self._api_url,
            "streamUrl": stream_payload["url"],
            "streamingReady": bool(stream_payload["available"]),
            "streamingActive": bool(stream_payload["active"]),
            "streamCodec": stream_payload["codec"],
            "streamLastError": stream_payload["last_error"],
            "outputDevice": self.current_output_device_description(),
            "outputDeviceId": self.current_output_device_id(),
            "needsAudioReset": self._needs_audio_reset,
            "shutdownWhenPlaylistEnds": self.shutdown_when_playlist_ends,
            "sleepWhenPlaylistEnds": self.sleep_when_playlist_ends,
        }
        with self._snapshot_lock:
            self._snapshot = payload
