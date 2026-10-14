
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./index.css";

const API_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

const EXAMPLES = [
  {
    icon: "◈",
    title: "Query my database",
    description: "Explore payment methods using SQL.",
    prompt: "Show me the different payment methods in the database",
    type: "sql",
  },
  {
    icon: "↗",
    title: "Extract from an API",
    description: "Fetch API data and save it as CSV.",
    prompt:
      "Extract data from https://pokeapi.co/api/v2/pokemon and save it as CSV",
    type: "etl",
  },
  {
    icon: "✳",
    title: "Select specific columns",
    description: "Keep only the fields you need.",
    prompt:
      "Extract data from https://pokeapi.co/api/v2/pokemon, keep the name and url fields, remove duplicates, and save as CSV",
    type: "etl",
  },
  {
    icon: "⤧",
    title: "Clean and transform data",
    description: "Ask for a specific transformation.",
    prompt:
      "Extract data from https://pokeapi.co/api/v2/pokemon, keep the name and url columns, remove duplicate rows, and save the transformed result as CSV",
    type: "etl",
  },
];

function Icon({ children }) {
  return <span className="icon-mark" aria-hidden="true">{children}</span>;
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [files, setFiles] = useState([]);
  const [fileError, setFileError] = useState("");
  const [activeNav, setActiveNav] = useState("Home");

  
async function refreshFiles() {
  try {
    const response = await fetch(`${API_URL}/files`);

    if (!response.ok) {
      throw new Error("Could not load generated files.");
    }

    const data = await response.json();
    setFiles(data.files || []);
    setFileError("");
  } catch (error) {
    setFileError(error.message);
  }
}

  async function sendMessage(event) {
    event?.preventDefault();

    const text = question.trim();
    if (!text || loading) return;

    setMessages((previous) => [
      ...previous,
      { role: "user", content: text },
    ]);
    setQuestion("");
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: text,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : "The request failed."
        );
      }

      setMessages((previous) => [
        ...previous,
        { role: "assistant", content: data.answer },
      ]);

      await refreshFiles();
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `**Request failed.** ${error.message}\n\nCheck that the backend is running and that your API URL is correct.`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function startNewChat() {
    if (loading) return;

    setMessages([]);
    setQuestion("");
    setFiles([]);
    setFileError("");
    setActiveNav("Chat");
  }

  function goToSection(name, id) {
    setActiveNav(name);
    document.getElementById(id)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });

    if (name === "Files") refreshFiles();
  }

  function chooseExample(prompt) {
    setQuestion(prompt);
    setActiveNav("Chat");
    document.getElementById("chat")?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }

  return (
    <div className="app-shell">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <aside className="sidebar">
        <a className="brand" href="#home" onClick={() => setActiveNav("Home")}>
          <div className="brand-symbol">D<span>✳</span></div>
          <div>
            <div className="brand-name">
              Data <span>AI</span> Agent
            </div>
            <div className="brand-caption">Your data, your intelligence.</div>
          </div>
        </a>

        <div className="sidebar-label">WORKSPACE</div>

        <nav className="nav-menu">
          <button
            className={`nav-link ${activeNav === "Home" ? "active" : ""}`}
            onClick={() => goToSection("Home", "home")}
          >
            <Icon>⌂</Icon> Home
          </button>
          <button
            className={`nav-link ${activeNav === "Chat" ? "active" : ""}`}
            onClick={() => goToSection("Chat", "chat")}
          >
            <Icon>◉</Icon> Chat workspace
          </button>
          <button
            className={`nav-link ${activeNav === "Files" ? "active" : ""}`}
            onClick={() => goToSection("Files", "files")}
          >
            <Icon>▧</Icon> Session files
            {files.length > 0 && (
              <span className="nav-count">{files.length}</span>
            )}
          </button>
          <button
            className={`nav-link ${activeNav === "Guide" ? "active" : ""}`}
            onClick={() => goToSection("Guide", "guide")}
          >
            <Icon>⌘</Icon> How it works
          </button>
        </nav>

        <div className="sidebar-spacer" />

        <div className="sidebar-project">
          <div className="mini-orbit">✳</div>
          <div className="eyebrow">CURRENT PROJECT</div>
          <h3>Ola Data</h3>
          <p>
            Connected project data source for SQL questions and data workflows.
          </p>
          <div className="status-line">
            <span className="status-dot" />
            API configured per environment
          </div>
        </div>

        <div className="sidebar-footer">
          <div className="footer-mark">✦</div>
          <div>
            <strong>Built with LangGraph</strong>
            <p>Designed for data workflows.</p>
          </div>
        </div>
      </aside>

      <main className="main-content" id="home">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span><span className="crumb-divider">/</span>
            <strong>{activeNav}</strong>
          </div>
          <div className="topbar-actions">
            <span className="environment-tag">
              <span className="status-dot" /> AI WORKSPACE
            </span>
            <button
              className="button button-quiet"
              onClick={startNewChat}
              disabled={loading}
            >
              <span>＋</span> New chat
            </button>
          </div>
        </header>

        <section className="hero">
          <div className="hero-copy">
            <div className="overline"><span className="sparkle">✦</span> YOUR INTELLIGENT DATA ASSISTANT</div>
            <h1>
              Meet your data.
              <br />
              <span className="gradient-text">On your terms.</span>
            </h1>
            <p className="hero-description">
              Turn questions into insights. Query databases, extract data from
              APIs, and transform raw responses into useful files—all using
              natural language.
            </p>
            <div className="hero-actions">
              <button
                className="button button-primary"
                onClick={() => goToSection("Chat", "chat")}
              >
                Start exploring <span>↗</span>
              </button>
              <button
                className="button button-outline"
                onClick={() => goToSection("Guide", "guide")}
              >
                How it works <span>↓</span>
              </button>
            </div>
            <div className="hero-capabilities">
              <span><i>◈</i> Natural-language SQL</span>
              <span><i>✳</i> ETL workflows</span>
              <span><i>▧</i> CSV output</span>
            </div>
          </div>

          <div className="hero-art" aria-label="Data flowing through an AI workflow">
            <div className="art-glow" />
            <div className="orbit orbit-a" />
            <div className="orbit orbit-b" />
            <div className="orbit orbit-c" />
            <div className="art-node node-database"><span>▤</span><small>DATA</small></div>
            <div className="art-node node-api"><span>⌘</span><small>API</small></div>
            <div className="art-node node-file"><span>▧</span><small>CSV</small></div>
            <div className="ai-core">
              <div className="core-antenna" />
              <div className="core-face">
                <span className="core-eye" />
                <span className="core-eye" />
                <span className="core-smile" />
              </div>
              <div className="core-base" />
            </div>
            <div className="art-caption">From raw data to ready-to-use.</div>
            <span className="art-star star-a">✦</span>
            <span className="art-star star-b">·</span>
            <span className="art-star star-c">✧</span>
          </div>
        </section>

        <section className="project-notice">
          <div className="notice-icon">i</div>
          <div>
            <strong>Current project: Ola Data</strong>
            <p>
              This application is currently configured to work with Ola Data
              for database questions. For ETL tasks, you can also provide a
              supported API URL in your prompt.
            </p>
          </div>
          <span className="notice-badge">PROJECT INFO</span>
        </section>

        <section className="section-block" id="guide">
          <div className="section-heading">
            <div>
              <div className="overline">A SIMPLE WORKFLOW</div>
              <h2>From API to insight in three steps.</h2>
              <p>No need to write a complete ETL script yourself. Describe the outcome you want.</p>
            </div>
            <span className="section-index">01 / GUIDE</span>
          </div>

          <div className="workflow-grid">
            <article className="workflow-card workflow-purple">
              <div className="step-top">
                <div className="step-icon">↗</div>
                <span className="step-number">STEP 01</span>
              </div>
              <h3>Provide a source</h3>
              <p>Give the agent an API URL and describe what data you want.</p>
              <div className="example-snippet">
                <span>EXAMPLE PROMPT</span>
                Extract data from https://pokeapi.co/api/v2/pokemon
              </div>
            </article>

            <article className="workflow-card workflow-blue">
              <div className="step-top">
                <div className="step-icon">⤧</div>
                <span className="step-number">STEP 02</span>
              </div>
              <h3>Describe the transformation</h3>
              <p>Request columns, filtering, duplicate removal, or other supported cleaning operations.</p>
              <div className="example-snippet">
                <span>EXAMPLE PROMPT</span>
                Keep name and url. Remove duplicate rows.
              </div>
            </article>

            <article className="workflow-card workflow-mint">
              <div className="step-top">
                <div className="step-icon">▧</div>
                <span className="step-number">STEP 03</span>
              </div>
              <h3>Get your output</h3>
              <p>Ask for CSV output, then download generated files from this session.</p>
              <div className="example-snippet">
                <span>YOUR RESULT</span>
                A downloadable CSV, when the workflow succeeds.
              </div>
            </article>
          </div>
        </section>

        <section className="section-block examples-section" id="examples">
          <div className="section-heading">
            <div>
              <div className="overline">GET STARTED FASTER</div>
              <h2>What would you like to do?</h2>
              <p>Choose a starting point. You can edit the prompt before sending it.</p>
            </div>
            <span className="section-index">02 / EXAMPLES</span>
          </div>

          <div className="example-grid">
            {EXAMPLES.map((example) => (
              <button
                className={`example-card ${example.type}`}
                key={example.title}
                onClick={() => chooseExample(example.prompt)}
              >
                <div className="example-card-top">
                  <span className="example-icon">{example.icon}</span>
                  <span className="example-arrow">↗</span>
                </div>
                <h3>{example.title}</h3>
                <p>{example.description}</p>
                <span className="example-use">Use this prompt <span>→</span></span>
              </button>
            ))}
          </div>
        </section>

        <section className="chat-panel section-block" id="chat">
          <div className="chat-panel-heading">
            <div className="chat-heading-icon">✳</div>
            <div>
              <div className="overline">YOUR WORKSPACE</div>
              <h2>Talk to your data.</h2>
              <p>Ask a question, provide an API URL, or describe a transformation.</p>
            </div>
            <div className="chat-session-tag">SHARED WORKSPACE</div>
          </div>

          <div className="messages-area">
            {messages.length === 0 ? (
              <div className="empty-state">
                <div className="empty-orbit"><span>✳</span></div>
                <h3>Your next insight starts here.</h3>
                <p>
                  Try a database question or provide an API URL with clear
                  instructions for extraction and transformation.
                </p>
                <div className="suggestion-pills">
                  <button onClick={() => chooseExample(EXAMPLES[0].prompt)}>Explore database <span>↗</span></button>
                  <button onClick={() => chooseExample(EXAMPLES[2].prompt)}>Extract and clean <span>↗</span></button>
                </div>
              </div>
            ) : (
              <div className="message-list">
                {messages.map((message, index) => (
                  <article
                    key={`${index}-${message.role}`}
                    className={`message-row ${message.role}`}
                  >
                    <div className="message-avatar">
                      {message.role === "user" ? "Y" : "✳"}
                    </div>
                    <div className="message-body">
                      <div className="message-author">
                        {message.role === "user" ? "YOU" : "DATA AI AGENT"}
                      </div>
                      {message.role === "user" ? (
                        <div className="message-text">{message.content}</div>
                      ) : (
                        <div className="markdown-content">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {message.content}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                  </article>
                ))}
                {loading && (
                  <div className="thinking-indicator">
                    <span /><span /><span />
                    <p>Working through your request...</p>
                  </div>
                )}
              </div>
            )}
          </div>

          <form className="composer" onSubmit={sendMessage}>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask a question or paste an API URL..."
              disabled={loading}
              rows={2}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  sendMessage(event);
                }
              }}
            />
            <div className="composer-bottom">
              <span><span className="composer-dot" /> Natural language input · Shift + Enter for a new line</span>
              <button
                className="button button-primary send-button"
                type="submit"
                disabled={loading || !question.trim()}
              >
                {loading ? "Working..." : "Send request"} <span>↗</span>
              </button>
            </div>
          </form>
          <p className="privacy-note">
            Results depend on your configured backend, data source, and model credentials.
          </p>
        </section>

        <section className="section-block files-section" id="files">
          <div className="section-heading">
            <div>
              <div className="overline">YOUR OUTPUTS</div>
              <h2>Generated files.</h2>
              <p>Files created in the shared workspace appear here.</p>
            </div>
            <button className="button button-outline" onClick={() => refreshFiles()}>
              ↻ Refresh files
            </button>
          </div>

          {fileError && <div className="inline-error">{fileError}</div>}

          {files.length > 0 ? (
            <div className="file-list">
              {files.map((file) => (
                <div className="file-item" key={file.path}>
                  <div className="file-icon">▧</div>
                  <div className="file-info">
                    <strong>{file.name}</strong>
                    <span>{file.path}</span>
                  </div>
                  <a
                    className="file-download"
                    href={`${API_URL}${file.download_url}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download ↓
                  </a>
                </div>
              ))}
            </div>
          ) : (
            <div className="files-empty">
              <span>▧</span>
              <div>
                <strong>No generated files yet</strong>
                <p>Run an ETL request, then refresh this section.</p>
              </div>
            </div>
          )}
          <p className="files-disclaimer">
            Session files are temporary and may be removed after inactivity or a server restart.
            Download important outputs promptly.
          </p>
        </section>

        <section className="section-block about-section" id="about">
          <div className="about-main">
            <div className="overline">UNDER THE HOOD</div>
            <h2>One workspace.<br /><span className="gradient-text">Multiple data tasks.</span></h2>
            <p>
              Data AI Agent uses a LangGraph-powered agent workflow to route
              requests to database analysis or ETL tasks. The frontend sends
              your request to a FastAPI backend and displays the response.
            </p>
          </div>
          <div className="feature-stack">
            <div><span>01</span><div><strong>Natural-language interaction</strong><p>Describe the question or desired data output.</p></div></div>
            <div><span>02</span><div><strong>SQL and ETL workflows</strong><p>Route supported requests to the relevant agent.</p></div></div>
            <div><span>03</span><div><strong>Session-based downloads</strong><p>Find generated files and download them.</p></div></div>
          </div>
        </section>

        <footer className="page-footer">
          <a className="footer-brand" href="#home">Data <span>AI</span> Agent</a>
          <span>Extract thoughtfully. Transform clearly. Analyze confidently.</span>
          <button onClick={() => goToSection("Home", "home")}>Back to top ↑</button>
        </footer>
      </main>
    </div>
  );
}