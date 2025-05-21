import os
import argparse
import glob
import shutil

def merge_file_chunks(filename_pattern, output_file):
    """
    Merge file chunks into a single output file.
    
    Args:
        filename_pattern: Pattern to match chunk files (e.g., "example.mp4.*")
        output_file: Path to the output file
    """
    # Get a list of all chunk files matching the pattern
    chunk_files = sorted(glob.glob(filename_pattern), 
                          key=lambda x: int(x.split('.')[-1]))
    
    if not chunk_files:
        print(f"Error: No chunk files found matching pattern '{filename_pattern}'")
        return False
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    print(f"Merging {len(chunk_files)} chunks into {output_file}...")
    
    # Merge chunks into the output file
    with open(output_file, 'wb') as outfile:
        for chunk_file in chunk_files:
            print(f"Processing chunk: {chunk_file}")
            with open(chunk_file, 'rb') as infile:
                shutil.copyfileobj(infile, outfile)
    
    print(f"Successfully merged chunks into {output_file}")
    return True

def main():
    parser = argparse.ArgumentParser(description='Merge file chunks')
    parser.add_argument('--pattern', required=True, help='Pattern to match chunk files (e.g., "downloads/example.mp4.*")')
    parser.add_argument('--output', required=True, help='Path to the output file')
    
    args = parser.parse_args()
    
    merge_file_chunks(args.pattern, args.output)

if __name__ == "__main__":
    main()