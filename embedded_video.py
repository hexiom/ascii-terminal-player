from argparse import ArgumentParser, ArgumentTypeError
import os, curses, threading, simpleaudio as sa
import sys, cv2, re
import numpy as np
from pathlib import Path
from datetime import datetime
from time import sleep, perf_counter

PY_FIGLET_FONT = "banner"

HAS_PYFIGLET = True
HAS_PYSUBS = True

try:
    import pyfiglet
except ImportError:
    HAS_PYFIGLET = False

try:
    import pysubs2
except ImportError:
    HAS_PYSUBS = False

class SubtitleState:
    def __init__(self, subs_file):
        self.subs = subs_file
        self.current = 0
        self.active = []
        self.cached = []
        self.stale = False
    
    def update(self, time_ms: float):
        old_len = len(self.active)
        prev_current = self.current

        while self.current < len(self.subs) and self.subs[self.current].start <= time_ms:
            self.active.append(self.subs[self.current])
            self.current += 1
        
        self.active[:] = [s for s in self.active if s.end > time_ms]
        self.stale = self.current != prev_current or len(self.active) != old_len
    
    def set_fps(self, fps: float):
        old_fps = self.subs.fps

        if (old_fps is not None):
            self.subs = self.subs.transform_framerate(old_fps, fps)

class VideoStream:
    def __init__(self, stdscr, cap: cv2.VideoCapture, audio_file: str|None = None, subs_path: str|None = None, is_debug: bool = False):
        self.is_debug = is_debug
        self.scr = stdscr
        self.cap = cap
        self.t0 = -1
        self.exit_request = False
        self.elapsed_time = 0
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.total_frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = self.total_frame_count / self.fps
        self.audio_thread = None
        self.has_subs = False
        self.video_subs: SubtitleState|None = None
        self.frame_counter_before_update = 0
        self.frame_counter_update_timer = 0
        self.last_updated_fps_counter = -1
        self.last_rendered_frame = -1
        self.last_frame_delta = -1

        if (not self.fps or self.fps <= 0):
            self.fps = 30.0
        
        self.time_step = 1 / self.fps

        if (audio_file):
            self.audio_thread = threading.Thread(target=thread_audio, args=(audio_file, is_debug,), daemon=True)

        if (subs_path):
            valid_subs, subs_file = load_subtitles(subs_path, self.fps)

            if (valid_subs):
                self.has_subs = True
                self.video_subs = subs_file

    def async_start(self):
        if (self.audio_thread):
            self.audio_thread.start()
    
    def set_fps(self, new_fps: int):
        if (new_fps <= 0):
            return

        self.fps = new_fps
        self.time_step = 1 / self.fps

        if (self.has_subs):
            self.video_subs.set_fps(new_fps)
    
    def should_end(self):
        return self.elapsed_time >= self.duration
    
    def time_to_frameno(self, elapsed_time: float):
        return round(elapsed_time * self.fps)
    
    def should_rerender(self):
        current_frame = self.time_to_frameno(self.elapsed_time)
        return current_frame != self.last_rendered_frame

    def time_update(self):
        frame = self.time_to_frameno(self.elapsed_time)
        elapsed_time_ms = self.elapsed_time * 1000
        
        self.t0 = perf_counter()
        self.last_rendered_frame = frame
        
        if (self.has_subs):
            self.video_subs.update(elapsed_time_ms)

    def complete_frame(self, t1: float):
        time_step = self.time_step
        real_t0 = perf_counter()
        dt = max(0, t1 - self.t0)
        
        self.last_frame_delta = dt - time_step

        # Limit framerate
        if (dt < time_step):
            time_to_wait = time_step - dt

            if (time_to_wait >= 0.001):
                sleep(time_to_wait)
        
        real_dt = dt + (perf_counter() - real_t0)
        self.elapsed_time += real_dt
            
        self.frame_counter_before_update += 1
        self.frame_counter_update_timer += real_dt

        while (self.frame_counter_update_timer >= 1):
            self.frame_counter_update_timer -= 1

            self.last_updated_fps_counter = self.frame_counter_before_update
            self.frame_counter_before_update = 0
    
    def read_current_frame(self):
        return self.cap.read()
    
    def pop_input(self):
        try:
            return self.input_queue.get_nowait()
        except:
            return -1

def thread_audio(audio_path: str, is_verbose: bool):
    try:
        audio_obj = sa.WaveObject.from_wave_file(audio_path)

        play_obj = audio_obj.play()
        play_obj.wait_done()
    except Exception as e:
        if (is_verbose):
            print(f"AUDIO EXCEPTION: {e}")

def resource_path(rel):
    if hasattr(sys, "frozen"):
        return Path(sys.executable).parent / rel
    return Path(__file__).parent / rel

def load_subtitles(sub_path: str, target_fps: int):
    try:
        subs = pysubs2.load(sub_path, encoding="utf-8")
    
        if (subs.fps is not None):
            subs = subs.transform_framerate(subs.fps, target_fps)

        return (True, SubtitleState(subs))
    except Exception as e:
        return (False, None)

def time_duration_str(seconds: int):
    minutes, sec = divmod(int(seconds), 60)
    
    return f"{minutes:02d}:{sec:02d}"

def render_subs(stdscr, width, height, subtitle_state):
    active_subtitles = subtitle_state.active
    subs_start_x = width // 2
    subs_start_y = (height * 5) // 6

    dy = 0
    
    active_sublines = subtitle_state.cached

    if (subtitle_state.stale):
        subtitle_state.stale = False
        active_sublines = [s.text.replace("\\N", "\n").splitlines() for s in active_subtitles]

        subtitle_state.cached = active_sublines

    for i, sub_lines in enumerate(active_sublines):
        sub_y = subs_start_y + dy
        line_y = 0

        for line in sub_lines:
            sub_width = len(line)
            line_x = max(0, subs_start_x - sub_width // 2)
            sub_line_y = sub_y + line_y

            line_y += 1

            if (sub_line_y < 0 or sub_line_y >= height):
                break

            line_content = f" {line} "
            j = 0

            while (j < len(line_content) and line_x + j <= width - 4):
                char = line_content[j]

                if (not char.isascii()):
                    while not char.isascii() and j < len(line_content):
                        j += 1
                        char = line_content[j]
                    continue

                stdscr.addch(sub_line_y, line_x + j, char)
                j += 1
            
            if (line_x + len(line_content) > width - 1):
                stdscr.addstr(sub_line_y, width - 4, "...")
        
        dy -= 1

        if (i < len(active_sublines) - 1):
            next_sub = active_sublines[i + 1]
            extra_lines = len(next_sub)
            dy -= extra_lines

def create_frame(frame, width, height, is_inverted, ascii_list):
    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) / 255

    if (is_inverted):
        gray = 1 - gray

    ascii_indices = np.round(gray * (len(ascii_list)-1)).astype(np.uint8)
    screen_buffer = ascii_list[ascii_indices]

    return screen_buffer

def render_video_details(stdscr, video_stream: VideoStream):
    debug_info_height = 1
    elapsed_time = video_stream.elapsed_time
    video_fps = video_stream.fps
    video_duration = video_stream.duration
    is_debug = video_stream.is_debug
    current_frame = int(elapsed_time * video_fps)
    total_frame_count = round(video_duration * video_fps)

    if (is_debug):
        stdscr.addstr(debug_info_height, 2, f" Frame {current_frame} / {total_frame_count} ")
        debug_info_height += 1

    stdscr.addstr(debug_info_height, 3, f" {time_duration_str(elapsed_time)} / {time_duration_str(video_duration)} ")
    debug_info_height += 2

    if (is_debug):
        if (video_stream.last_updated_fps_counter > 0):
            stdscr.addstr(debug_info_height, 4, f" FPS: {video_stream.last_updated_fps_counter} ")

            debug_info_height += 1

        stdscr.addstr(debug_info_height, 4, f" Frame delta: {(video_stream.last_frame_delta > 0 and "+" or "-")}{(abs(video_stream.last_frame_delta)*1000):.2f}ms ")
        debug_info_height += 1

def _main(stdscr):
    video_path = resource_path("_data/v0")
    audio_path = resource_path("_data/v1")
    subtitles_path = resource_path("_data/v2")
    is_debug = False
    ascii_set = " .:-=+*@%#"

    if (not os.path.exists(subtitles_path)):
        subtitles_path = None

    if (not os.path.exists(audio_path)):
        audio_path = None

    curses.curs_set(0)
    stdscr.clear()
    
    cap = cv2.VideoCapture(str(video_path))

    if (not cap.isOpened()):
        return (False, 2, "ERROR: Cannot open file. Please try again later.")
    
    video_stream = VideoStream(stdscr, cap, str(audio_path), subtitles_path, is_debug)
    ascii_list = np.array(list(ascii_set))
    video_stream.async_start()

    try:
        while not video_stream.exit_request:
            if (video_stream.should_end()):
                break

            if (video_stream.should_rerender()):
                video_stream.time_update()
                ret, frame = video_stream.read_current_frame()

                if (not ret):
                    continue

                term_height, term_width = stdscr.getmaxyx()
                screen_buffer = create_frame(frame, term_width, term_height, False, ascii_list)

                for y in range(term_height):
                    line = "".join(screen_buffer[y, :term_width-1])
                    stdscr.addstr(y, 0, line)

                render_video_details(stdscr, video_stream)

                if (video_stream.has_subs):
                    render_subs(stdscr, term_width, term_height, video_stream.video_subs)

                stdscr.refresh()

            video_stream.complete_frame(perf_counter())
    except Exception as e:
        return (False, 1, str(e))
        
def main():
    stdscr = curses.initscr()

    curses.noecho()
    curses.cbreak()

    stdscr.keypad(1)

    try:
        curses.start_color()
    except:
        pass

    exit_code = 1

    try:
        (success, exit_code, print_msg) = _main(stdscr)
    finally:
        curses.nocbreak()
        curses.echo()
        curses.endwin()
        
        return exit_code

    if (not success and print_msg):
        print(str(print_msg))

if __name__ == "__main__":
    code = main()
    sys.exit(code)
