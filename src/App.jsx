// App.jsx
import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import "./App.css";
import emailjs from '@emailjs/browser';

const MODEL_METRICS = [
  { label: "Accuracy", value: "0.692 \u00B1 0.027" },
  { label: "Overall recall", value: "0.564 \u00B1 0.047" },
  { label: "Overall precision", value: "0.699 \u00B1 0.062" },
  { label: "Weighted F1-score", value: "0.677 \u00B1 0.028" },
  { label: "Class 2 recall", value: "0.351 \u00B1 0.136" },
  { label: "Class 2 precision", value: "0.748 \u00B1 0.161" },
  { label: "Class 2 F1-score", value: "0.463 \u00B1 0.130" },
];

const getPredictionValue = (prediction) => {
  if (Array.isArray(prediction)) return prediction[0];
  return prediction ?? "";
};

const getResultRows = (result, mode) => {
  if (!result) return [];
  if (mode === "single") {
    return [{ ...result, CAS: result.CAS || result.dataset?.CAS }];
  }
  return Array.isArray(result.results) ? result.results : [];
};

const formatProbability = (value) => {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(1)}%`;
};

const formatDecimal = (value) => {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return value.toFixed(3);
};

const formatFeatureList = (features) => {
  if (Array.isArray(features)) return features.join("; ");
  return features || "";
};

const csvEscape = (value) => {
  if (value === null || value === undefined) return "";

  const text = Array.isArray(value)
    ? value.join("; ")
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);

  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }

  return text;
};

// Website loading animation component
const WebsiteLoader = () => {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(timer);
          return 100;
        }
        return prev + Math.floor(Math.random() * 10) + 1;
      });
    }, 200);

    return () => clearInterval(timer);
  }, []);

  return (
    <div className="website-loader">
      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{ width: `${Math.min(progress, 100)}%` }}
        ></div>
      </div>
      <div className="website-loader-spinner"></div>
      <div className="website-loader-text">
        Loading Chemical Prediction Tool
      </div>
      <div className="loader-status">{Math.min(progress, 100)}% Complete</div>
    </div>
  );
};

// About Model Component
const AboutModel = () => {
  return (
    <div className="about-model-container">
      <h2 className="section-title">About Our Model</h2>
      <div className="about-model-content">
        <div className="model-section">
          <h3 className="model-subtitle">How It Works</h3>
          <p>
            Our system uses RDKit-generated molecular features to predict the bioconcentration 
            behavior of chemical compounds. RDKit is a powerful cheminformatics toolkit with a 
            wide range of features for molecular manipulation and analysis. These features 
            numerically represent chemical structure properties, allowing for accurate 
            predictions using machine learning models.
          </p>
        </div>

        <div className="model-section">
          <h3 className="model-subtitle">Prediction Classes</h3>
          <p>
            Based on the chemical structure, the model classifies compounds into one of the 
            following categories:
          </p>
          <div className="prediction-classes">
            <div className="prediction-class">
              <div className="class-indicator orange"></div>
              <div className="class-details">
                <h4>Class 1: Inert Chemicals (Moderately Toxic)</h4>
                <p>Tend to accumulate in lipids</p>
              </div>
            </div>
            <div className="prediction-class">
              <div className="class-indicator red"></div>
              <div className="class-details">
                <h4>Class 2: Specifically Bioconcentrating Chemicals (Highly Toxic)</h4>
                <p>Actively interact with proteins or biological tissues</p>
              </div>
            </div>
            <div className="prediction-class">
              <div className="class-indicator green"></div>
              <div className="class-details">
                <h4>Class 3: Less Bioconcentrating Chemicals (Least Toxic)</h4>
                <p>Are typically metabolized or eliminated from the organism</p>
              </div>
            </div>
          </div>
        </div>

        <div className="model-section">
          <h3 className="model-subtitle">Voting Classifier Model Performance</h3>
          <p className="model-description">
            The Voting Classifier combines predictions from Random Forest, Logistic
            Regression, Support Vector Classifier, and Gradient-Boosted Decision Tree
            models. It generates a confidence score for each bioconcentration mechanism
            class—Class 1, Class 2, and Class 3—and assigns the chemical to the class
            with the highest confidence score.
          </p>
          <div className="metrics-grid">
            {MODEL_METRICS.map((metric) => (
              <div className="metric-item" key={metric.label}>
                <span className="metric-label">{metric.label}</span>
                <strong className="metric-value">{metric.value}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="model-section">
          <p className="model-goal">
            Our goal is to assist in the risk assessment of chemical exposure by providing 
            reliable predictions of bioconcentration behavior based on chemical features. This
            prediction should be interpreted as a screening-level result. The model is intended
            to provide an additional prediction perspective and should not be used as a
            standalone basis for regulatory classification.
          </p>
        </div>
      </div>
    </div>
  );
};

const App = () => {
  const [currentPage, setCurrentPage] = useState("home");
  const [loading, setLoading] = useState(true);

  // Simulate website loading
  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(false);
    }, 1500);

    return () => clearTimeout(timer);
  }, []);

  // Page transition loading effect
  const [pageLoading, setPageLoading] = useState(false);

  const handlePageChange = (page) => {
    setPageLoading(true);
    setTimeout(() => {
      setCurrentPage(page);
      setPageLoading(false);
    }, 300);
  };

  if (loading) {
    return <WebsiteLoader />;
  }

  return (
    <div className="app-container">
      <Header setCurrentPage={handlePageChange} currentPage={currentPage} />
      <main className="main-content">
        {pageLoading ? (
          <div className="page-loader">
            <div className="loading-spinner"></div>
            <div className="loading-text">
              Loading{" "}
              {currentPage === "home"
                ? "Home"
                : "Contact"}
              Page...
            </div>
          </div>
        ) : (
          <>
            {currentPage === "home" && (
              <div className="home-container">
                <div className="home-content-wrapper">
                  <div className="home-left-column">
                    <AboutModel />
                  </div>
                  <div className="home-right-column">
                    <PredictForm />
                  </div>
                </div>
              </div>
            )}
            {currentPage === "contact" && <ContactPage />}
          </>
        )}
      </main>
      <Footer />
    </div>
  );
};

const Header = ({ setCurrentPage, currentPage }) => {
  return (
    <header className="header">
      <div
        className="header-title"
        onClick={() => setCurrentPage("home")}
        style={{ cursor: "pointer" }}
      >
        Chemical Prediction Tool
      </div>
      <nav className="header-nav">
        <a
          href="#"
          className={`nav-link ${currentPage === "home" ? "active" : ""}`}
          onClick={(e) => {
            e.preventDefault();
            setCurrentPage("home");
          }}
        >
          Home
        </a>

        <a
          href="#"
          className={`nav-link ${currentPage === "contact" ? "active" : ""}`}
          onClick={(e) => {
            e.preventDefault();
            setCurrentPage("contact");
          }}
        >
          Contact Us
        </a>
      </nav>
    </header>
  );
};

const ContactPage = () => {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    message: "",
  });
  const [formStatus, setFormStatus] = useState({
    sending: false,
    sent: false,
    error: null,
  });

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  // Put these in a .env file for security in production
  const SERVICE_ID = 'service_1vv6vcs';
  const TEMPLATE_ID = 'template_sf2ulje';
  const PUBLIC_KEY = 'RpOoe-FYhaf3ykQvo';

  const handleSubmit = (e) => {
    e.preventDefault();
    setFormStatus({ sending: true, sent: false, error: null });

    emailjs
      .send(
        SERVICE_ID,
        TEMPLATE_ID,
        {
          name: formData.name,
          email: formData.email,
          message: formData.message,
        },
        PUBLIC_KEY
      )
      .then(
        (response) => {
          console.log('SUCCESS!', response.status, response.text);
          setFormStatus({ sending: false, sent: true, error: null });
          setFormData({ name: "", email: "", message: "" });

          setTimeout(() => {
            setFormStatus((prev) => ({ ...prev, sent: false }));
          }, 5000);
        },
        (error) => {
          console.error('FAILED...', error);
          setFormStatus({
            sending: false,
            sent: false,
            error: 'Failed to send message. Please try again.',
          });
        }
      );
  };

  return (
    <div className="contact-container">
      <h2 className="section-title">Contact Us</h2>
      <div className="contact-cards">
        <div className="contact-card">
          <div className="contact-icon person-icon"></div>
          <h3>Shashwat Dhayade</h3>
          <p>Lead Developer</p>
        </div>

        <div className="contact-card">
          <div className="contact-icon email-icon"></div>
          <h3>Email</h3>
          <p>
            <a href="mailto:ssd6515@mavs.uta.edu">ssd6515@mavs.uta.edu</a>
          </p>
        </div>
      </div>

      <div className="contact-message">
        <h3>Send us a message</h3>
        <form className="contact-form" onSubmit={handleSubmit}>
          <div className="form-row">
            <input
              type="text"
              name="name"
              value={formData.name}
              onChange={handleInputChange}
              placeholder="Your Name"
              className="contact-input"
              required
            />
            <input
              type="email"
              name="email"
              value={formData.email}
              onChange={handleInputChange}
              placeholder="Your Email"
              className="contact-input"
              required
            />
          </div>
          <textarea
            name="message"
            value={formData.message}
            onChange={handleInputChange}
            placeholder="Your Message"
            className="contact-textarea"
            required
          ></textarea>

          {formStatus.error && (
            <div className="form-error">{formStatus.error}</div>
          )}
          {formStatus.sent && (
            <div className="form-success">Message sent successfully!</div>
          )}

          <button
            type="submit"
            className="contact-submit"
            disabled={formStatus.sending}
          >
            {formStatus.sending ? "Sending..." : "Send Message"}
          </button>
        </form>
      </div>
    </div>
  );
};

const Footer = () => {
  return (
    <footer className="footer">
      <div className="footer-content">© 2026 Copyright Shashwat Dhayade</div>
    </footer>
  );
};

// Loading animation component
const LoadingAnimation = ({ message }) => {
  return (
    <div className="loading-container">
      <div className="loading-spinner"></div>
      <div className="loading-text">{message}</div>
    </div>
  );
};

const PredictForm = () => {
  // UI mode: single vs batch
  const [mode, setMode] = useState("single");

  // Single prediction state
  const [cas, setCas] = useState("");

  // Batch (CSV) state
  const [file, setFile] = useState(null);

  // Common result & error
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Reference for results container to scroll to
  const resultsRef = useRef(null);

  // Endpoints
  const DIRECT_API =
    "https://slna812zu3.execute-api.us-east-2.amazonaws.com/directvaluetoxclass"; // your single‐item lambda URL
  const PRESIGN_API =
    "https://2dz3enyezd.execute-api.us-east-2.amazonaws.com/default/toxprojectfileupload"; // your presign URL generator lambda
  const BATCH_API =
    "https://3m8lbkhdgf.execute-api.us-east-2.amazonaws.com/toxclassfile"; // <— your new CSV‐processing lambda URL

  // Reset form when mode changes
  useEffect(() => {
    setCas("");
    setFile(null);
    setResult(null);
    setError("");
  }, [mode]);

  // Handle file selection
  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0] || null;
    setFile(selectedFile);
    setError("");
    setResult(null);
  };

  // Reset form handler
  const resetForm = () => {
    setCas("");
    setFile(null);
    setResult(null);
    setError("");
  };

  // Effect to scroll to results when they appear
  useEffect(() => {
    if (result && resultsRef.current) {
      // Scroll to results with a slight delay to ensure rendering is complete
      setTimeout(() => {
        resultsRef.current.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 300);
    }
  }, [result]);

  // Submit handler
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);

    try {
      let payload;

      if (mode === "single") {
        if (!cas) {
          throw new Error("Please provide a CAS value");
        }
        payload = { cas };
      } else {
        if (!file) {
          throw new Error("Please select a CSV file first");
        }

        // 1) GET a presigned URL + key
        const presignRes = await axios({
          method: "GET", // or 'POST' if your backend expects JSON
          url: PRESIGN_API,
          params: { Key: file.name }, // or in body if POST
        });
        const { uploadURL, filename: s3Key } = presignRes.data;

        // 2) PUT the CSV into S3
        const putRes = await fetch(uploadURL, {
          method: "PUT",
          headers: {
            "Content-Type": file.type || "text/csv",
          },
          body: file,
        });
        if (!putRes.ok) throw new Error("S3 upload failed");

        // 3) now send the S3 key to your batch‐processing API
        payload = { s3Key };
      }

      // Add a small delay to show the loading animation
      await new Promise((resolve) => setTimeout(resolve, 800));

      // 4) hit your prediction endpoint
      const apiRes = await fetch(mode === "single" ? DIRECT_API : BATCH_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!apiRes.ok) {
        const raw = await apiRes.text();
        let data; try { data = JSON.parse(raw); } catch { data = {}; }
        const msg = data.error || data.message || raw || "Prediction failed";
        throw new Error(msg);
      }

      setResult(await apiRes.json());
    } catch (err) {
      setError(err.message);
    }

    setLoading(false);
  };
  const handleDownloadSample = () => {
    const link = document.createElement("a");
    link.href = "/sample.csv";
    link.download = "sample.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };
  // Download results
  // Download results as CSV including all RDKit features
  const handleDownloadResults = () => {
    if (!result) return;

    const resultRows = getResultRows(result, mode);
    if (!resultRows.length) return;

    const sampleDataset = resultRows.find((row) => row.dataset)?.dataset || {};
    const featureKeys = Object.keys(sampleDataset).filter((k) => k !== "CAS");
    const probabilityKeys = [
      ...new Set(
        resultRows.flatMap((row) => Object.keys(row.class_probabilities || {}))
      ),
    ];
    const diagnosticColumns = [
      ["cas", (row) => row.CAS || row.dataset?.CAS],
      ["prediction", (row) => getPredictionValue(row.prediction)],
      ["max_prediction_probability", (row) => row.max_prediction_probability],
      ["ad_status", (row) => row.ad_status],
      ["prediction_reliability", (row) => row.prediction_reliability],
      ["knn_mean_distance", (row) => row.knn_mean_distance],
      ["ad_distance_threshold", (row) => row.ad_distance_threshold],
      ["inside_distance_ad", (row) => row.inside_distance_ad],
      ["feature_range_warning", (row) => row.feature_range_warning],
      [
        "n_features_outside_training_range",
        (row) => row.n_features_outside_training_range,
      ],
      [
        "fraction_features_outside_training_range",
        (row) => row.fraction_features_outside_training_range,
      ],
      [
        "features_outside_training_range",
        (row) => formatFeatureList(row.features_outside_training_range),
      ],
    ];

    const header = [
      ...diagnosticColumns.map(([column]) => column),
      ...probabilityKeys,
      ...featureKeys,
    ];
    const rows = resultRows.map((row) => [
      ...diagnosticColumns.map(([, getValue]) => getValue(row)),
      ...probabilityKeys.map((key) => row.class_probabilities?.[key]),
      ...featureKeys.map((key) => row.dataset?.[key]),
    ]);

    const csvContent =
      [header, ...rows].map((r) => r.map(csvEscape).join(",")).join("\n") +
      "\n";

    // Trigger download
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = mode === "single" ? "prediction_full.csv" : "batch_predictions_full.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const resultRows = getResultRows(result, mode);
  const singleResult = resultRows[0];

  const renderProbabilityList = (classProbabilities) => {
    const entries = Object.entries(classProbabilities || {});
    if (!entries.length) return null;

    return (
      <div className="probability-list">
        {entries.map(([className, probability]) => (
          <div className="probability-item" key={className}>
            <span>{className.replace("class_", "Class ")}</span>
            <strong>{formatProbability(probability)}</strong>
          </div>
        ))}
      </div>
    );
  };

  const renderReliabilityBadge = (value) => (
    <span className={`reliability-badge reliability-${String(value || "").toLowerCase()}`}>
      {value || "N/A"}
    </span>
  );

  const renderSingleResult = () => {
    if (!singleResult) return null;

    return (
      <div className="single-result-summary">
        <div className="result-summary-grid">
          <div className="result-stat">
            <span>Predicted class</span>
            <strong>{getPredictionValue(singleResult.prediction)}</strong>
          </div>
          <div className="result-stat">
            <span>Model confidence</span>
            <strong>{formatProbability(singleResult.max_prediction_probability)}</strong>
          </div>
          <div className="result-stat">
            <span>Applicability domain</span>
            <strong>{singleResult.ad_status || "N/A"}</strong>
          </div>
          <div className="result-stat">
            <span>Reliability</span>
            {renderReliabilityBadge(singleResult.prediction_reliability)}
          </div>
        </div>
        <div className="ad-detail-row">
          <span>kNN distance: {formatDecimal(singleResult.knn_mean_distance)}</span>
          <span>AD threshold: {formatDecimal(singleResult.ad_distance_threshold)}</span>
          <span>
            Outside-range features:{" "}
            {singleResult.n_features_outside_training_range ?? "N/A"}
          </span>
        </div>
        {renderProbabilityList(singleResult.class_probabilities)}
      </div>
    );
  };

  const renderBatchResults = () => {
    if (!resultRows.length) return null;

    return (
      <div className="results-table-wrapper">
        <table className="results-table">
          <thead>
            <tr>
              <th>CAS</th>
              <th>Prediction</th>
              <th>Confidence</th>
              <th>Applicability domain</th>
              <th>Reliability</th>
            </tr>
          </thead>
          <tbody>
            {resultRows.map((row, index) => (
              <tr key={`${row.CAS || row.dataset?.CAS || "row"}-${index}`}>
                <td>{row.CAS || row.dataset?.CAS}</td>
                <td>{getPredictionValue(row.prediction)}</td>
                <td>{formatProbability(row.max_prediction_probability)}</td>
                <td>{row.ad_status || "N/A"}</td>
                <td>{renderReliabilityBadge(row.prediction_reliability)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };


  return (
    <div className="predict-container">
      <h2 className="section-title">Chemical Prediction</h2>

      {/* Mode Selector */}
      <div className="mode-selector">
        <label className="radio-label">
          <input
            type="radio"
            value="single"
            checked={mode === "single"}
            onChange={() => setMode("single")}
            className="radio-input"
          />
          <span className="radio-text">Single Prediction</span>
        </label>
        <label className="radio-label">
          <input
            type="radio"
            value="batch"
            checked={mode === "batch"}
            onChange={() => setMode("batch")}
            className="radio-input"
          />
          <span className="radio-text">Batch (CSV) Prediction</span>
        </label>
      </div>

      {mode === "batch" && (
        <div style={{ margin: "1em 0" }}>
          <button
            type="button"
            onClick={handleDownloadSample}
            className="download-sample-button"
          >
            Download Sample CSV
          </button>
        </div>
      )}

      <form onSubmit={handleSubmit} className="prediction-form">
        {mode === "single" ? (
          <div className="form-fields">
            <div className="form-group">
              <label htmlFor="cas" className="form-label">
                CAS (Chemical Abstracts Service - Chemical Identification
                Number):
              </label>
              <input
                id="cas"
                type="text"
                placeholder="e.g., 100-02-7"
                value={cas}
                onChange={(e) => setCas(e.target.value)}
                required
                className="form-input"
              />
            </div>
          </div>
        ) : (
          <div className="form-group">
            <label htmlFor="csvUpload" className="form-label">
              Upload CSV (Max 10 Chemicals, CAS column only):
            </label>
            <input
              id="csvUpload"
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              className="file-input"
            />
          </div>
        )}

        <div className="button-group">
          <button type="submit" disabled={loading} className="submit-button">
            {loading
              ? mode === "single"
                ? "Predicting…"
                : "Uploading & Processing…"
              : mode === "single"
              ? "Predict"
              : "Run Batch"}
          </button>
          {result && (
            <button type="button" onClick={resetForm} className="reset-button">
              Reset
            </button>
          )}
        </div>
      </form>

      {error && <p className="error-message">{error}</p>}

      {loading && (
        <LoadingAnimation
          message={
            mode === "single"
              ? "Analyzing chemical data..."
              : "Processing CSV file..."
          }
        />
      )}

      {result && (
        <div ref={resultsRef} className="results-container">
          <h3 className="results-title">Results</h3>
          {mode === "single" ? renderSingleResult() : renderBatchResults()}

          <details className="raw-results">
            <summary>Full JSON response</summary>
            <pre className="results-content">
              {JSON.stringify(result, null, 2)}
            </pre>
          </details>

          <button
            type="button"
            onClick={handleDownloadResults}
            className="download-results-button"
          >
            Download Results as CSV
          </button>

        </div>
      )}
    </div>
  );
};

export default App;
