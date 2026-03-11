using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Launcher
{
    [STAThread]
    static void Main()
    {
        string python = @"C:\Program Files\Python314\python.exe";
        string aio = @"C:\Program Files\aio\kiosk";

        string updater = Path.Combine(aio, "updater_win.py");
        string activation = Path.Combine(aio, "activation_win.py");

        // Log to ProgramData so we can diagnose "nothing happened" cases
        string logDir = @"C:\\ProgramData\\aio\\logs";
        string logFile = Path.Combine(logDir, "launcher.log");

        void Log(string message)
        {
            try
            {
                Directory.CreateDirectory(logDir);
                File.AppendAllText(logFile, $"[{DateTime.Now:O}] {message}{Environment.NewLine}");
            }
            catch
            {
                // Never block launch due to logging failures
            }
        }

        Log("Launcher started.");

        if (!File.Exists(python))
        {
            string msg = "Python runtime not found:\\n" + python;
            Log(msg);
            MessageBox.Show(msg, "AIO Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        if (!Directory.Exists(aio))
        {
            string msg = "Kiosk directory not found:\\n" + aio;
            Log(msg);
            MessageBox.Show(msg, "AIO Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        string scriptToRun;
        if (File.Exists(updater))
        {
            scriptToRun = updater;
            Log("Using updater_win.py");
        }
        else if (File.Exists(activation))
        {
            scriptToRun = activation;
            Log("Using activation_win.py");
        }
        else
        {
            string msg = "Neither updater_win.py nor activation_win.py found in:\\n" + aio;
            Log(msg);
            MessageBox.Show(msg, "AIO Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        try
        {
            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = python,
                Arguments = "-u \"" + scriptToRun + "\"",
                WorkingDirectory = aio,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            Log($"Launching: {psi.FileName} {psi.Arguments} (cwd={psi.WorkingDirectory})");

            Process proc = Process.Start(psi);
            if (proc != null)
            {
                Log($"Process started. PID={proc.Id}");
            }
            else
            {
                Log("Process.Start returned null.");
            }
        }
        catch (Exception ex)
        {
            Log("Exception while launching: " + ex.ToString());
            MessageBox.Show("Failed to launch AIO system:\n" + ex.Message,
                "Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}