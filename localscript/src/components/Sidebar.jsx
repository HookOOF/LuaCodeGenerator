import { useState, useEffect } from 'react'
import { listSessions } from '../api'
import ChatInstance from './ChatInstance'
import GpuMonitor from './GpuMonitor'

export default function Sidebar({ activeSessionId, onSelectSession, onNewChat, refreshKey }) {
    const [sessions, setSessions] = useState([]);

    useEffect(() => {
        listSessions()
            .then(setSessions)
            .catch(console.error);
    }, [refreshKey]);

    return (
        <div className="flex flex-col bg-neutral-900 h-screen w-[15vw] shrink-0">
            <div className="flex items-center p-5 gap-3">
                <img src="logo.svg" alt="LocalScript" />
                <p className="flex-1 font-bold text-3xl truncate select-none">
                    LocalScript
                </p>
            </div>
            <button
                onClick={onNewChat}
                className="flex w-[calc(100%-2.5rem)] justify-center text-3xl mx-5 border text-neutral-300 border-neutral-600 rounded-[7px]
                hover:backdrop-brightness-150 mt-6 mb-6 cursor-pointer"
            >
                <div className="pt-2 pb-2 select-none">+ New Chat</div>
            </button>
            <div className="flex-1 flex flex-col gap-1 overflow-y-auto px-5 min-h-0
                [scrollbar-width:thin] [scrollbar-color:theme(colors.neutral.700)_transparent]">
                {sessions.map((s) => (
                    <ChatInstance
                        key={s.id}
                        id={s.id}
                        title={s.title || s.last_message || 'New chat'}
                        isActive={s.id === activeSessionId}
                        onClick={() => onSelectSession(s.id)}
                    />
                ))}
            </div>
            <GpuMonitor />
        </div>
    )
}
