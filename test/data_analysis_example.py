import pandas as pd
import matplotlib.pyplot as plt
import glob
import os

def analyze_latest_result():
    # Find the newest CSV file in the results directory
    list_of_files = glob.glob('results/*.csv')
    if not list_of_files:
        print("No CSV files found in 'results' folder. Run test_runner.py first.")
        return

    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"Analyzing {latest_file}...")

    df = pd.read_csv(latest_file)

    # Calculate basic stats
    total_time = df['system_time'].iloc[-1] - df['system_time'].iloc[0]
    total_packets = len(df)

    print(f"Total Test Time: {total_time:.2f} seconds")
    print(f"Total Telemetry Packets Captured: {total_packets}")

    # Normalize time to start at 0
    time_seq = df['system_time'] - df['system_time'].iloc[0]

    # Create subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)

    # Plot 1: RC Channels over time
    ax1.plot(time_seq, df['rc_pitch'], label='Pitch (Forward/Back)', color='blue')
    ax1.plot(time_seq, df['rc_roll'], label='Roll (Left/Right)', color='green')
    ax1.plot(time_seq, df['rc_throttle'], label='Throttle (Height)', color='red')
    ax1.plot(time_seq, df['rc_arm'], label='Arm (Active/Inactive)', color='black', linestyle='--')

    ax1.set_title(f"RC Channel Activity - {df['test_name'].iloc[0]} ({df['test_method'].iloc[0]})")
    ax1.set_ylabel("RC Value (1000-2000)")
    ax1.legend()
    ax1.grid(True)

    # Plot 2: FC Telemetry (Current & Pitch Angle)
    ax2.plot(time_seq, df['fc_pitch_angle'], label='FC Pitch Angle (deg)', color='purple')
    ax2.plot(time_seq, df['fc_current'], label='FC Current Draw (A)', color='orange')

    ax2.set_title("Flight Controller Telemetry")
    ax2.set_xlabel("Time (seconds)")
    ax2.set_ylabel("Value")
    ax2.legend()
    ax2.grid(True)

    plt.tight_layout()

    # Save the figure
    plot_filename = latest_file.replace('.csv', '.png')
    plt.savefig(plot_filename)
    print(f"Plot saved to {plot_filename}")
    plt.show()

if __name__ == "__main__":
    analyze_latest_result()
