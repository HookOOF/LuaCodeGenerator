import { useState, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import Chat from './components/Chat'

function App() {
    const [activeSessionId, setActiveSessionId] = useState(() => {
        const params = new URLSearchParams(window.location.search);
        return params.get('session') || null;
    });
    const [refreshKey, setRefreshKey] = useState(0);

    const refreshSessions = useCallback(() => {
        setRefreshKey((k) => k + 1);
    }, []);

    const handleSelectSession = useCallback((id) => {
        setActiveSessionId(id);
        const url = new URL(window.location);
        url.searchParams.set('session', id);
        window.history.pushState({}, '', url);
    }, []);

    const handleNewChat = useCallback(() => {
        setActiveSessionId(null);
        const url = new URL(window.location);
        url.searchParams.delete('session');
        window.history.pushState({}, '', url);
    }, []);

    return (
        <div className="flex flex-row">
            <Sidebar
                activeSessionId={activeSessionId}
                onSelectSession={handleSelectSession}
                onNewChat={handleNewChat}
                refreshKey={refreshKey}
            />
            <Chat
                sessionId={activeSessionId}
                onSessionCreated={(id) => {
                    handleSelectSession(id);
                    refreshSessions();
                }}
            />
        </div>
    )
}

export default App
