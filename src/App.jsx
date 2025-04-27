// App.jsx
import React, { useState } from 'react';
import axios from 'axios';

const PredictForm = () => {
  // UI mode: single vs batch
  const [mode, setMode] = useState('single');

  // Single prediction state
  const [cas, setCas] = useState('');
  const [logKOW, setLogKOW] = useState('');

  // Batch (CSV) state
  const [file, setFile] = useState(null);

  // Common result & error
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Endpoints
  const DIRECT_API  = 'https://slna812zu3.execute-api.us-east-2.amazonaws.com/directvaluetoxclass';          // your single‐item lambda URL
  const PRESIGN_API = 'https://2dz3enyezd.execute-api.us-east-2.amazonaws.com/default/toxprojectfileupload';          // your presign URL generator lambda
  const BATCH_API   = 'https://3m8lbkhdgf.execute-api.us-east-2.amazonaws.com/toxclassfile';          // <— your new CSV‐processing lambda URL

  // Handle file selection
  const handleFileChange = e => {
    setFile(e.target.files[0]);
    setError('');
    setResult(null);
  };

  // Submit handler
  const handleSubmit = async e => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setResult(null);

    try {
      let payload;

      if (mode === 'single') {
        if (!cas || !logKOW) {
          throw new Error('Please provide both CAS and logKOW values');
        }
        payload = { cas, logKOW };

      } else {
        if (!file) {
          throw new Error('Please select a CSV file first');
        }

        // 1) GET a presigned URL + key
        const presignRes = await axios({
          method: 'GET',         // or 'POST' if your backend expects JSON
          url: PRESIGN_API,
          params: { Key: file.name }  // or in body if POST
        });
        const { uploadURL, filename: s3Key } = presignRes.data;

        // 2) PUT the CSV into S3
        const putRes = await fetch(uploadURL, {
          method: 'PUT',
          headers: {
            'Content-Type': file.type || 'text/csv'
          },
          body: file
        });
        if (!putRes.ok) throw new Error('S3 upload failed');

        // 3) now send the S3 key to your batch‐processing API
        payload = { s3Key };
      }

      // 4) hit your prediction endpoint
      const apiRes = await fetch(
        mode === 'single' ? DIRECT_API : BATCH_API,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }
      );
      if (!apiRes.ok) {
        const err = await apiRes.json();
        throw new Error(err.error || 'Prediction failed');
      }

      setResult(await apiRes.json());
    } catch (err) {
      setError(err.message);
    }

    setLoading(false);
  };

  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h2>Chemical Prediction</h2>

      {/* Mode Selector */}
      <div style={{ marginBottom: '1rem' }}>
        <label style={{ marginRight: '1rem' }}>
          <input
            type="radio"
            value="single"
            checked={mode === 'single'}
            onChange={() => setMode('single')}
          /> Single Prediction
        </label>
        <label>
          <input
            type="radio"
            value="batch"
            checked={mode === 'batch'}
            onChange={() => setMode('batch')}
          /> Batch (CSV) Prediction
        </label>
      </div>

      <form onSubmit={handleSubmit} style={{ margin: '1rem' }}>
        {mode === 'single' ? (
          <>
            <div style={{ marginBottom: '1rem' }}>
              <label htmlFor="cas">CAS:</label>{' '}
              <input
                id="cas"
                type="text"
                placeholder="e.g., 100-02-7"
                value={cas}
                onChange={e => setCas(e.target.value)}
                required
              />
            </div>
            <div style={{ marginBottom: '1rem' }}>
              <label htmlFor="logKOW">logKOW:</label>{' '}
              <input
                id="logKOW"
                type="number"
                placeholder="e.g., 1.91"
                value={logKOW}
                onChange={e => setLogKOW(e.target.value)}
                required
              />
            </div>
          </>
        ) : (
          <div style={{ marginBottom: '1rem' }}>
            <label htmlFor="csvUpload">Upload CSV:</label>{' '}
            <input
              id="csvUpload"
              type="file"
              accept=".csv"
              onChange={handleFileChange}
            />
          </div>
        )}

        <button type="submit" disabled={loading}>
          {loading
            ? mode === 'single'
              ? 'Predicting…'
              : 'Uploading & Processing…'
            : mode === 'single'
              ? 'Predict'
              : 'Run Batch'}
        </button>
      </form>

      {error && <p style={{ color: 'red' }}>{error}</p>}

      {result && (
        <div style={{ textAlign: 'left', display: 'inline-block', marginTop: '2rem' }}>
          <h3>Results</h3>
          <pre style={{
            background: '#f4f4f4',
            padding: '1rem',
            borderRadius: '5px',
            maxHeight: '400px',
            overflowY: 'auto'
          }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
};

export default PredictForm;
