import sys, os

def main():
    argc = len(sys.argv)

    if (argc < 2):
        base_name = os.path.basename(os.getcwd())
        print(f"USAGE: {base_name} [COMPRESSED_FILE]")
        return 1
    
    file_name = sys.argv[1]
    img_width = -1
    img_height = -1
    
    with open("bad_apple.bin", "rb") as f:
        i = 0

        frame_count = int.from_bytes(f.read(4))
        img_width = int.from_bytes(f.read(4))
        img_height = int.from_bytes(f.read(4))

        while (i < frame_count):
            stream_len = int.from_bytes(f.read(4))
            stream_data = f.read(stream_len)

            img_data.append(stream_data)

            i += 1

    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)