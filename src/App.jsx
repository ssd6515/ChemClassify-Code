// App.jsx
import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import "./App.css";

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
                : currentPage === "method"
                ? "Method"
                : "Contact"}{" "}
              Page...
            </div>
          </div>
        ) : (
          <>
            {currentPage === "home" && <PredictForm />}
            {currentPage === "method" && <MethodPage />}
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
          className={`nav-link ${currentPage === "method" ? "active" : ""}`}
          onClick={(e) => {
            e.preventDefault();
            setCurrentPage("method");
          }}
        >
          Method
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

const MethodPage = () => {
  return (
    <div className="method-container" style={{ width: "100%" }}>
      <h2 className="section-title">How to Fetch logKOW</h2>

      <div className="kow-formula">
        <h3>KOW Formula:</h3>
        <img
          src="/images/img_0.jpeg"
          alt="KOW Formula: Concentration of chemical in octanol / Concentration of chemical in water"
          className="formula-image"
        />
      </div>

      <div className="method-section">
        <h3>Method 1: PubChem</h3>
        <p className="method-description">
          PubChem is a database of chemical molecules and their activities
          against biological assays. It is maintained by the National Center for
          Biotechnology Information (NCBI).
        </p>
        <p className="method-link">
          Link:{" "}
          <a
            href="https://pubchem.ncbi.nlm.nih.gov/"
            target="_blank"
            rel="noopener noreferrer"
          >
            https://pubchem.ncbi.nlm.nih.gov/
          </a>
        </p>

        <div className="method-steps">
          <div className="method-step">
            <p>1. Enter desired chemical name</p>
            <img
              src="/images/img_1.png"
              alt="PubChem search interface"
              className="method-image"
            />
          </div>

          <div className="method-step">
            <p>2. Click on the desired chemical</p>
            <img
              src="/images/img_2.png"
              alt="PubChem search results"
              className="method-image"
            />
          </div>

          <div className="method-step">
            <p>3. Navigate to the chemical information page</p>
            <img
              src="/images/img_3.png"
              alt="PubChem chemical information page"
              className="method-image"
            />
          </div>

          <div className="method-step">
            <p>4. Search for values which represent logKOW</p>
            <img
              src="/images/img_4.png"
              alt="PubChem logKOW values"
              className="method-image"
            />
          </div>

          <div className="method-step">
            <p>5. Find the logKOW value</p>
            <img
              src="/images/img_5.png"
              alt="PubChem logKOW value details"
              className="method-image"
            />
          </div>
        </div>
      </div>

      <div className="method-section">
        <h3>Method 2: Dragon Software</h3>
        <p className="method-description">
          Dragon Software is a tool for calculating molecular descriptors used
          in QSAR analysis.
        </p>
        <p className="method-link">
          Link:{" "}
          <a
            href="https://chm.kode-solutions.net/pf/knime-extension-for-dragon-7-0/"
            target="_blank"
            rel="noopener noreferrer"
          >
            https://chm.kode-solutions.net/pf/knime-extension-for-dragon-7-0/
          </a>
        </p>

        <div className="method-steps">
          <div className="method-step">
            <p>Dragon Software Interface</p>
            <img
              src="/images/img_6.png"
              alt="Dragon Software Interface"
              className="method-image"
            />
          </div>
        </div>

        <div className="method-note">
          <p>
            <strong>NOTE:</strong> Registration is required to use Dragon 7.0
            software
          </p>
        </div>
      </div>
    </div>
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

  const handleSubmit = (e) => {
    e.preventDefault();
    setFormStatus({ sending: true, sent: false, error: null });

    // In a real application, you would use a service like EmailJS, Formspree, or your own backend
    // Here we'll simulate sending an email with a timeout
    setTimeout(() => {
      try {
        // This is where you would integrate with an email service
        // For demonstration, we're just simulating success
        console.log("Email would be sent to: ssd6515@mavs.uta.edu");
        console.log("Form data:", formData);

        // Simulate success
        setFormStatus({ sending: false, sent: true, error: null });

        // Reset form after successful submission
        setFormData({ name: "", email: "", message: "" });

        // Reset success message after 5 seconds
        setTimeout(() => {
          setFormStatus((prev) => ({ ...prev, sent: false }));
        }, 5000);
      } catch (error) {
        setFormStatus({
          sending: false,
          sent: false,
          error: "Failed to send message. Please try again.",
        });
      }
    }, 1500);
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

        <div className="contact-card">
          <div className="contact-icon phone-icon"></div>
          <h3>Phone</h3>
          <p>+1(469)927-4741</p>
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
      <div className="footer-content">© 2025 Copyright Shshwat Dhayade</div>
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
  const [logKOW, setLogKOW] = useState("");

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
    setLogKOW("");
    setFile(null);
    setResult(null);
    setError("");
  }, [mode]);

  // Handle file selection
  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setError("");
    setResult(null);
  };

  // Reset form handler
  const resetForm = () => {
    setCas("");
    setLogKOW("");
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
        if (!cas || !logKOW) {
          throw new Error("Please provide both CAS and logKOW values");
        }
        payload = { cas, logKOW };
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
        const err = await apiRes.json();
        throw new Error(err.error || "Prediction failed");
      }

      setResult(await apiRes.json());
    } catch (err) {
      setError(err.message);
    }

    setLoading(false);
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
            <div className="form-group">
              <label htmlFor="logKOW" className="form-label">
                logKOW:
              </label>
              <input
                id="logKOW"
                type="number"
                placeholder="e.g., 1.91"
                value={logKOW}
                onChange={(e) => setLogKOW(e.target.value)}
                required
                className="form-input"
              />
            </div>
          </div>
        ) : (
          <div className="form-group">
            <label htmlFor="csvUpload" className="form-label">
              Upload CSV:
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
          <pre className="results-content">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
};

export default App;
