from argparse import ArgumentParser, ArgumentTypeError
import os, curses, threading, simpleaudio as sa
import sys, cv2, re
import numpy as np
from datetime import datetime
from math import floor, ceil
from time import sleep, perf_counter

LOG_FORMAT = "log/video-player.%s.log"
DEFAULT_ASCII_SET = " .:-=+*@%#"
DEFAULT_FPS = 24
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

def load_subtitles(sub_path: str, target_fps: int):
    try:
        subs = pysubs2.load(sub_path, encoding="utf-8")
    
        if (subs.fps is not None):
            subs = subs.transform_framerate(subs.fps, target_fps)

        return (True, SubtitleState(subs))
    except Exception as e:
        return (False, None)

def get_banner(text: str):
    if HAS_PYFIGLET:
        ascii_art = pyfiglet.figlet_format(text, PY_FIGLET_FONT)

        return ascii_art
    
    return text

def get_video_name(video_path: str):
    video_path = os.path.splitext(os.path.basename(video_path))[0]
    video_path = re.sub(r"[_\-\.\s]+", " ", video_path).replace(".", "").strip()

    return video_path.title()

def timestamp_str():
    return datetime.now().strftime("%Y-%m-%d.%H:%M")

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

    if (video_stream.has_subs):
        stdscr.addstr(debug_info_height, 4, " HAS SUBS ")
        debug_info_height += 1

def _main(stdscr, args):
    is_debug = args.debug
    ascii_set = args.ascii

    curses.curs_set(0)
    stdscr.clear()
    
    input_filename = args.input_file
    cap = cv2.VideoCapture(input_filename)

    if (not cap.isOpened()):
        return (False, 2, "ERROR: Cannot open video file...")
    
    video_stream = VideoStream(stdscr, cap, args.audio, args.subs, is_debug)

    if (args.title_screen):
        banner_title = args.title_banner or get_video_name(input_filename)
        banner = get_banner(banner_title)
        banner_lines = banner.split("\n")
        banner_height = len(banner_lines)
        banner_width = max(map(lambda l: len(l), banner_lines))

        tex_keypress = "Press any key to start..."

        stdscr.nodelay(True)
        stdscr.timeout(100)

        while True:
            term_height, term_width = stdscr.getmaxyx()
            banner_y = (term_height // 4)
            banner_bottom = min(banner_y + banner_height, term_height)
            tex_keypress_y = banner_bottom + 4

            banner_x = term_width // 2 - banner_width // 2
            tex_keypress_x = term_width // 2 - len(tex_keypress) // 2

            for i in range(banner_height):
                line = banner_lines[i]
                stdscr.addstr(banner_y + i, banner_x, line)
            
            stdscr.addstr(tex_keypress_y, tex_keypress_x, tex_keypress)
            stdscr.refresh()

            ch = stdscr.getch()

            if (ch != -1):
                break
        
        stdscr.nodelay(False)
        stdscr.timeout(-1)
        
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
                # stdscr.clear()

                screen_buffer = create_frame(frame, term_width, term_height, args.invert, ascii_list)

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
        

def dimension_argument(value):
    value = ''.join(value.split())
    comma_separated = value.split(",")

    try:
        if (len(comma_separated) == 1 or not comma_separated[1]):
            return (int(comma_separated[0]), -1)
        width = int(comma_separated[0])
        height = int(comma_separated[1])

        return (width, height)
    except ValueError as e:
        raise ArgumentTypeError(f"Invalid argument. The dimensions must be of type integer.")

def main():
    parser = ArgumentParser(description="A script to run a .bin compressed video file in the terminal window.")
    parser.add_argument("input_file", help="The input file.")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--invert", action="store_true", help="Whether or not to invert the ascii set, essentially reversing the lightness values.")
    parser.add_argument("--subs", help="Adds subtitles to the player. Must specify a subtitles file.")
    parser.add_argument("--audio", help="Adds audio to the player. Only .wav and raw pcm files are supported.")
    parser.add_argument("--ascii", default=DEFAULT_ASCII_SET, help=f"The ascii set to use for the player. From darkest pixel to lightest pixel. The default is \"{DEFAULT_ASCII_SET}\"")
    parser.add_argument("--title-screen", action="store_true", help="Shows a title screen before the actual video. It waits for user input in this screen.")
    parser.add_argument("--title-banner", help="The title shown on the title screen. If not specified, uses a transformed version of the video name. Only useful if --title-screen is set.")

    args = parser.parse_args()

    if (not os.path.exists(args.input_file)):
        print(f"ERROR: File \"{os.path.basename(args.input_file)}\" does not exist.")
        return 1
        
    if (args.subs and not os.path.exists(args.subs)):
        print(f"The subtitles file \"{os.path.basename(args.subs)}\" does not exist.")
        return 1

    if (args.audio and not os.path.exists(args.audio)):
        print(f"The audio file \"{os.path.basename(args.audio)}\" does not exist.")
        return 1
    
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
        (success, exit_code, print_msg) = _main(stdscr, args)
        
        if (not success and print_msg):
            print(str(print_msg))
    finally:
        curses.nocbreak()
        curses.echo()
        curses.endwin()
        
        return exit_code

if __name__ == "__main__":
    code = main()
    sys.exit(code)
