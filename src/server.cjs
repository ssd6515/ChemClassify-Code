// server.cjs
const express = require('express');
const fileUpload = require('express-fileupload');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const app = express();
const uploadDir = path.join(__dirname, 'uploads');

// Create uploads directory if it doesn't exist
if (!fs.existsSync(uploadDir)) {
  fs.mkdirSync(uploadDir);
}

app.use(express.json());
app.use(fileUpload());

// Set predict.py full path
const predictScriptPath = path.join(__dirname, 'predict.py');
console.log('Using predict.py path:', predictScriptPath);

// Endpoint for single chemical predictions
app.post('/predictSingle', (req, res) => {
  const { cas, logKOW } = req.body;
  if (!cas || !logKOW) {
    return res.status(400).json({ error: 'Missing CAS or logKOW' });
  }

  // Spawn Python with cwd set to __dirname
  const pythonProcess = spawn('python', [predictScriptPath, '--mode', 'single'], { cwd: __dirname });

  let result = '';
  pythonProcess.stdout.on('data', (data) => {
    result += data.toString();
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error('Python stderr:', data.toString());
  });

  pythonProcess.on('close', () => {
    try {
      const output = JSON.parse(result);
      res.json(output);
    } catch (err) {
      res.status(500).json({ error: 'Error processing prediction' });
    }
  });

  // Write JSON input to Python stdin
  pythonProcess.stdin.write(JSON.stringify({ cas, logKOW }));
  pythonProcess.stdin.end();
});

// Endpoint for multiple chemical predictions
app.post('/predictMultiple', (req, res) => {
  if (!req.files || !req.files.file) {
    return res.status(400).json({ error: 'No file uploaded' });
  }
  const file = req.files.file;
  const filePath = path.join(uploadDir, file.name);

  // Move the file to the uploads directory
  file.mv(filePath, (err) => {
    if (err) {
      return res.status(500).json({ error: 'Error saving file' });
    }
    // Spawn Python with cwd set to __dirname and pass the file path argument
    const pythonProcess = spawn('python', [predictScriptPath, '--mode', 'multiple', '--input', filePath], { cwd: __dirname });

    let result = '';
    pythonProcess.stdout.on('data', (data) => {
      result += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      console.error('Python stderr:', data.toString());
    });

    pythonProcess.on('close', () => {
      try {
        const output = JSON.parse(result);
        res.json(output);
      } catch (err) {
        res.status(500).json({ error: 'Error processing prediction' });
      }
    });
  });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
