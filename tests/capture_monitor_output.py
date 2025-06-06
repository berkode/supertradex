#!/usr/bin/env python3
"""
Capture Monitor Output - Run monitor for limited time and capture output
"""

import subprocess
import time
import signal
import os
import sys

def run_monitor_with_timeout(timeout_seconds=90):
    """Run the monitor for a limited time and capture output"""
    print(f"🚀 Starting two token monitor for {timeout_seconds} seconds...")
    
    # Start the monitor process
    try:
        # Activate venv and run the monitor
        process = subprocess.Popen(
            ["bash", "-c", "source ./.venv/bin/activate && python test_two_token_quick.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        print(f"✅ Monitor started (PID: {process.pid})")
        print(f"⏰ Will run for {timeout_seconds} seconds...")
        print("📊 Output:")
        print("-" * 60)
        
        start_time = time.time()
        
        # Read output line by line with timeout
        while True:
            # Check if timeout reached
            if time.time() - start_time > timeout_seconds:
                print("\n" + "="*60)
                print(f"⏰ Timeout reached ({timeout_seconds}s)")
                print("🛑 Stopping monitor...")
                
                # Terminate the process
                process.terminate()
                
                # Wait for it to terminate, or kill it
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("   Process didn't terminate, killing...")
                    process.kill()
                    process.wait()
                
                print("✅ Monitor stopped")
                break
            
            # Check if process ended
            if process.poll() is not None:
                print(f"\n📋 Monitor process ended with code: {process.returncode}")
                break
            
            # Read output with timeout
            try:
                line = process.stdout.readline()
                if line:
                    print(line.rstrip())
                else:
                    time.sleep(0.1)  # Small delay if no output
            except Exception as e:
                print(f"Error reading output: {e}")
                break
        
        # Read any remaining output
        remaining_output, _ = process.communicate()
        if remaining_output:
            print("📋 Remaining output:")
            print(remaining_output)
        
        print("="*60)
        print("🏁 Monitor capture complete!")
        
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        if 'process' in locals():
            process.terminate()
    except Exception as e:
        print(f"❌ Error running monitor: {e}")

if __name__ == "__main__":
    run_monitor_with_timeout(90)  # Run for 90 seconds 