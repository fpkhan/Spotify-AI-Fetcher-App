import React, { useState, useEffect, useRef } from 'react';

function App() {
  const [status, setStatus] = useState("Ready to parse music inputs...");
  const [statusColor, setStatusColor] = useState("#8e8e8e");
  const [isRecording, setIsRecording] = useState(false);
  const [tracks, setTracks] = useState([]);
  const [textQuery, setTextQuery] = useState("");
  const [aiResponse, setAiResponse] = useState("");
  const [isRagLoading, setIsRagLoading] = useState(false);

  // Brand New States for Spotify Integration
  const [spotifyToken, setSpotifyToken] = useState(null);
  const [playlistName, setPlaylistName] = useState("My Semantic Vibe Mix");
  const [isExporting, setIsExporting] = useState(false);

  const statusPollInterval = useRef(null);

  // 1. Intercept Spotify OAuth Fragment Token on Component Mounting
  useEffect(() => {
    const hash = window.location.hash;
    if (hash) {
      const tokenParam = hash.substring(1).split('&').find(elem => elem.startsWith('access_token'));
      if (tokenParam) {
        const accessToken = tokenParam.split('=')[1];
        setSpotifyToken(accessToken);
        localStorage.setItem('spotify_token', accessToken);
        window.location.hash = ''; // Clean up URL parameter trash smoothly
        setStatus("Spotify authorization token cached securely!");
        setStatusColor("#1db954");
      }
    } else {
      const savedToken = localStorage.getItem('spotify_token');
      if (savedToken) setSpotifyToken(savedToken);
    }
  }, []);

  const triggerSpotifyLogin = () => {
    window.location.href = "http://127.0.0.1:8000/api/login";
  };

  const disconnectSpotify = () => {
    localStorage.removeItem('spotify_token');
    setSpotifyToken(null);
    setStatus("Spotify account disconnected.");
    setStatusColor("#8e8e8e");
  };

  const handlePlaylistExport = async () => {
    if (!tracks || tracks.length === 0) return;
    setIsExporting(true);
    setStatus("Generating empty playlist container on your Spotify profile...");
    setStatusColor("#ff9800");

    // Gather unique track identifiers out of the active database list rows
    const trackIds = tracks.map(track => track.id);

    try {
      const response = await fetch("http://127.0.0.1:8000/api/create-playlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: spotifyToken,
          playlist_name: playlistName,
          track_ids: trackIds
        })
      });

      const data = await response.json();
      if (data.status === "success") {
        setStatus(`Playlist successfully seeded and published into active account!`);
        setStatusColor("#1db954");
        alert("Success! Your matching tracks have been pushed to Spotify.");
      } else {
        throw new Error(data.detail || "Playlist injection request dropped.");
      }
    } catch (err) {
      console.error(err);
      setStatus(`Export Error context: ${err.message}`);
      setStatusColor("#f44336");
      // Wipe stale session storage keys if token validation fails out
      if (err.message.includes("Expired") || err.message.includes("credential")) {
        localStorage.removeItem('spotify_token');
        setSpotifyToken(null);
      }
    } finally {
      setIsExporting(false);
    }
  };

  const startVoiceDictation = async () => {
    try {
      setIsRecording(true);
      setStatus("Microphone hot: Adjusting background noise...");
      setStatusColor("#ffeb3b"); 

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      let options = { mimeType: 'audio/webm;codecs=opus' };
      if (MediaRecorder.isTypeSupported('audio/mp4')) {
        options = { mimeType: 'audio/mp4' };
      }

      const mediaRecorder = new MediaRecorder(stream, options);
      const audioChunks = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunks.push(event.data);
      };

      mediaRecorder.onstop = async () => {
        setStatus("Processing voice dictation transcription...");
        setStatusColor("#ff9800"); 

        const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
        const formData = new FormData();
        const fileExt = mediaRecorder.mimeType.includes('mp4') ? 'mp4' : 'webm';
        formData.append("file", audioBlob, `query.${fileExt}`);

        statusPollInterval.current = setInterval(async () => {
          try {
            const res = await fetch("http://127.0.0.1:8000/api/query-status");
            const update = await res.json();
            setStatus(update.status);
          } catch (err) {
            console.error("Polling error:", err);
          }
        }, 400);

        try {
          const response = await fetch("http://127.0.0.1:8000/api/transcribe", {
            method: "POST",
            body: formData,
          });

          clearInterval(statusPollInterval.current);
          const result = await response.json();

          if (result.status === "success") {
            setTextQuery(result.text); 
            setStatus(`Dictation caught! Ready to submit semantic match.`);
            setStatusColor("#1db954");
          } else {
            throw new Error(result.message || "Failed voice capture.");
          }
        } catch (pipelineError) {
          setStatus(`Transcription Error: ${pipelineError.message}`);
          setStatusColor("#f44336");
        } finally {
          setIsRecording(false);
          clearInterval(statusPollInterval.current);
          stream.getTracks().forEach(track => track.stop());
        }
      };

      setStatus("Speak your vibe now...");
      setStatusColor("#1db954");
      mediaRecorder.start();

      setTimeout(() => {
        if (mediaRecorder.state === "recording") mediaRecorder.stop();
      }, 5000);

    } catch (err) {
      setStatus(`Failed to open audio channels: ${err.message}`);
      setStatusColor("#f44336");
      setIsRecording(false);
    }
  };

  const handleRAGSearch = async (e) => {
    e.preventDefault();
    if (!textQuery.trim()) return;

    setIsRagLoading(true);
    setAiResponse("");
    setTracks([]);
    
    try {
      const response = await fetch("http://127.0.0.1:8000/api/query-rag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: textQuery }),
      });

      const result = await response.json();
      if (result.status === "success") {
        setAiResponse(result.ai_response);
        setTracks(result.tracks);
        setStatus("Semantic search resolution successful!");
        setStatusColor("#1db954");
      } else {
        alert("RAG Pipeline execution block dropped.");
      }
    } catch (err) {
      console.error("Error executing RAG search:", err);
      setStatus(`Search failure: ${err.message}`);
      setStatusColor("#f44336");
    } finally {
      setIsRagLoading(false);
    }
  };

  useEffect(() => {
    return () => {
      if (statusPollInterval.current) clearInterval(statusPollInterval.current);
    };
  }, []);

  return (
    <div style={{
      maxWidth: '900px',
      margin: '40px auto',
      padding: '30px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      backgroundColor: '#121212',
      color: '#ffffff',
      borderRadius: '12px',
      boxShadow: '0 8px 24px rgba(0,0,0,0.5)'
    }}>
      <header style={{
        borderBottom: '1px solid #282828',
        paddingBottom: '15px',
        marginBottom: '30px',
        textAlign: 'center'
      }}>
        <h1 style={{ margin: 0, fontSize: '2rem', color: '#1db954' }}>
          Spotify AI Semantic Studio
        </h1>
        <div style={{
          marginTop: '6px',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: '10px',
          flexWrap: 'wrap'
        }}>
          <p style={{ margin: 0, color: '#b3b3b3', fontSize: '0.9rem' }}>
            Azure SQL Cloud Relational Search Integration • Connected via Docker Ecosystem
          </p>

          {/* SPOTIFY CONNECTION STATUS — small sleek pill, sits beside the subtitle */}
          {!spotifyToken ? (
            <button
              onClick={triggerSpotifyLogin}
              style={{ padding: '3px 10px', background: '#1DB954', color: '#fff', border: 'none', borderRadius: '12px', fontSize: '0.7rem', fontWeight: 'bold', cursor: 'pointer', whiteSpace: 'nowrap', lineHeight: '1.6' }}
            >
              🟢 Connect Spotify
            </button>
          ) : (
            <button
              onClick={disconnectSpotify}
              title="Click to disconnect this Spotify account"
              style={{ padding: '3px 10px', background: '#282828', color: '#1db954', border: '1px solid #1db954', borderRadius: '12px', fontSize: '0.7rem', fontWeight: 'bold', cursor: 'pointer', whiteSpace: 'nowrap', lineHeight: '1.6' }}
            >
              ✅ Connected
            </button>
          )}
        </div>
      </header>

      {/* Live Status Notifier Box */}
      <div style={{
        backgroundColor: '#181818',
        padding: '20px',
        borderRadius: '8px',
        borderLeft: `6px solid ${statusColor}`,
        marginBottom: '25px',
        transition: 'border-color 0.3s ease'
      }}>
        <div style={{ textTransform: 'uppercase', fontSize: '0.75rem', color: '#b3b3b3', marginBottom: '5px' }}>
          Pipeline Status Log Indicator
        </div>
        <p style={{ margin: 0, fontSize: '1.1rem', fontWeight: '500' }}>{status}</p>
      </div>
      
      {/* Ask Spotify AI Search Wrapper Block */}
      <div style={{ marginBottom: '35px', padding: '20px', background: '#181818', borderRadius: '8px', border: '1px solid #282828' }}>
          <h3 style={{ color: '#1DB954', marginTop: 0, marginBottom: '15px' }}>Ask Spotify AI Search</h3>
          
          <form onSubmit={handleRAGSearch} style={{ display: 'flex', gap: '12px', marginBottom: '15px' }}>
              <div style={{ position: 'relative', flex: 1, display: 'flex', alignItems: 'center' }}>
                  <input 
                      type="text"
                      value={textQuery}
                      onChange={(e) => setTextQuery(e.target.value)}
                      placeholder={isRecording ? "Listening closely to audio pitch..." : "Tell me a mood, genre vibe, or concept..."}
                      style={{ 
                          width: '100%', 
                          padding: '14px', 
                          paddingRight: '50px', 
                          borderRadius: '6px', 
                          border: 'none', 
                          background: '#282828', 
                          color: '#fff',
                          fontSize: '0.95rem'
                      }}
                  />
                  
                  <button
                      type="button"
                      onClick={startVoiceDictation}
                      disabled={isRecording}
                      title="Dictate Query via Microphone"
                      style={{
                          position: 'absolute',
                          right: '10px',
                          width: '34px',
                          height: '34px',
                          borderRadius: '50%',
                          border: 'none',
                          backgroundColor: isRecording ? '#f44336' : '#404040',
                          color: '#fff',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '1.1rem',
                          boxShadow: isRecording ? '0 0 10px #f44336' : 'none',
                          transition: 'all 0.2s ease'
                      }}
                  >
                      🎙️
                  </button>
              </div>

              <button 
                  type="submit" 
                  disabled={isRagLoading || isRecording}
                  style={{ 
                      padding: '12px 28px', 
                      background: '#1DB954', 
                      color: '#fff', 
                      border: 'none', 
                      borderRadius: '4px', 
                      cursor: (isRagLoading || isRecording) ? 'not-allowed' : 'pointer', 
                      fontWeight: 'bold',
                      fontSize: '0.95rem'
                  }}
              >
                  {isRagLoading ? "Thinking..." : "Search"}
              </button>
          </form>

          {/* AI Conversational Chat Bubble */}
          {aiResponse && (
              <div style={{ padding: '18px', background: '#242424', borderRadius: '6px', borderLeft: '4px solid #1DB954', color: '#b3b3b3', lineHeight: '1.6', whiteSpace: 'pre-wrap', fontSize: '0.95rem' }}>
                  <strong style={{ color: '#fff', display: 'block', marginBottom: '8px', fontSize: '1rem' }}>Spotify AI Recommendations:</strong>
                  {aiResponse}
              </div>
          )}
      </div>

      {/* Relational Query Output Layout Grid Table */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
          <h2 style={{ fontSize: '1.25rem', margin: 0, color: '#ffffff', fontWeight: '600' }}>Captured Track Grid Results</h2>
          
          {/* EXPORT BAR — only needs a track list; Spotify connection is handled in the header now */}
          {tracks.length > 0 && spotifyToken && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <input 
                type="text"
                value={playlistName}
                onChange={(e) => setPlaylistName(e.target.value)}
                style={{ padding: '6px 12px', background: '#282828', color: '#fff', border: '1px solid #404040', borderRadius: '4px', fontSize: '0.85rem' }}
              />
              <button 
                onClick={handlePlaylistExport}
                disabled={isExporting}
                style={{ padding: '8px 16px', background: '#ffffff', color: '#000', border: 'none', borderRadius: '20px', fontSize: '0.85rem', fontWeight: 'bold', cursor: isExporting ? 'not-allowed' : 'pointer' }}
              >
                {isExporting ? "Exporting..." : "Export to Spotify"}
              </button>
            </div>
          )}
        </div>

        {tracks.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', backgroundColor: '#181818', borderRadius: '8px', color: '#b3b3b3', border: '1px dashed #282828' }}>
            No matching relational tracks to display. Tap the microphone bubble or input custom keywords above.
          </div>
        ) : (
          <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid #282828' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', backgroundColor: '#181818' }}>
              <thead>
                <tr style={{ backgroundColor: '#282828', color: '#b3b3b3', fontSize: '0.85rem', textTransform: 'uppercase' }}>
                  <th style={{ padding: '14px 20px' }}>Track ID</th>
                  <th style={{ padding: '14px 20px' }}>Track Name</th>
                  <th style={{ padding: '14px 20px' }}>Artists</th>
                  <th style={{ padding: '14px 20px', textAlign: 'center' }}>Similarity Metric Score</th>
                </tr>
              </thead>
              <tbody>
                {tracks.map((track, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid #282828', fontSize: '0.95rem' }}>
                    <td style={{ padding: '14px 20px', fontFamily: 'monospace', color: '#888', fontSize: '0.85rem' }}>{track.id}</td>
                    <td style={{ padding: '14px 20px', fontWeight: '500', color: '#ffffff' }}>{track.name}</td>
                    <td style={{ padding: '14px 20px', color: '#b3b3b3' }}>{track.artists}</td>
                    <td style={{ padding: '14px 20px', textAlign: 'center', fontWeight: 'bold', color: '#1db954' }}>
                      Cosine Dist: {track.distance.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;