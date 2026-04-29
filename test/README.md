# Drone Test Framework

This folder contains scripts to test different control methods (Voice, EMG, Voice+EMG, Physical Controller) and gather telemetry data to generate plots for your poster.

## Files
- `test_sequences.json`: Defines the test sequences (from Easy to Expert). You can edit this file to add new tests.
- `test_runner.py`: The interactive prompter. It tells you what command to perform, verifies when the command is executed by the drone, and logs everything to a CSV file.
- `data_analysis_example.py`: A script that loads the latest CSV file and plots the RC channels over time using `matplotlib` and `pandas`.
- `results/`: Directory where all the CSV logs and plots are saved.

## How to Run a Test
1. Make sure the main stack is running (`Raspberry_Pi.py` and `ESP32_Firmware.js`).
2. Open a new terminal and navigate to the `test` directory:
   ```bash
   cd test
   ```
3. Run the test runner:
   ```bash
   python test_runner.py
   ```
4. Follow the on-screen prompts. Perform the actions (Takeoff, commands, Land) using your selected control method.
5. The test will automatically finish and save a CSV file in `test/results/`.

## Analyzing Data
To generate plots for your poster, run:
```bash
pip install pandas matplotlib
python data_analysis_example.py
```
This will read the most recently created CSV file and generate a `.png` plot of the RC channels.
