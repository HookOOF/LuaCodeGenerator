import { useState, useEffect, useRef } from 'react';
import { getMessages } from '../api';
import LoadingAnimation from './LoadingAnimation';

export default function ChatMessages({ sessionId, refreshKey, optimisticMsg, sending }) {
    const [messages, setMessages] = useState([]);
    const [loading, setLoading] = useState(true);
    const bottomRef = useRef(null);

    useEffect(() => {
        if (!sessionId) return;
        let cancelled = false;
        setLoading(true);

        const fetchWithRetry = async (retries = 2, delay = 300) => {
            for (let i = 0; i <= retries; i++) {
                try {
                    const msgs = await getMessages(sessionId);
                    if (!cancelled) setMessages(msgs);
                    return;
                } catch (err) {
                    if (i < retries) {
                        await new Promise(r => setTimeout(r, delay));
                    } else if (!cancelled) {
                        console.error(err);
                        setMessages([]);
                    }
                }
            }
        };

        fetchWithRetry().finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [sessionId, refreshKey]);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, optimisticMsg, sending]);

    if (loading && messages.length === 0) {
        return (
            <div className="flex items-center justify-center w-full">
                <LoadingAnimation />
            </div>
        );
    }

    const allMessages = optimisticMsg ? [...messages, optimisticMsg] : messages;

    return (
        <div className="flex flex-col gap-4 p-4 w-[80%] max-w-[85vw] h-full overflow-y-auto
            [scrollbar-width:thin] [scrollbar-color:theme(colors.neutral.700)_transparent]">
            {allMessages.map((msg, index) => (
                <div
                    key={msg.id || `opt-${index}`}
                    className={`p-3 rounded-lg max-w-[80%] ${
                        msg.role === 'user'
                            ? 'bg-amber-100 self-end text-right text-black'
                            : 'bg-neutral-800 self-start text-left text-white'
                    }`}
                >
                    <p className="text-lg whitespace-pre-wrap">{msg.content}</p>
                    {msg.lua_code && (
                        <pre className="mt-2 p-3 bg-neutral-900 text-green-400 rounded text-sm overflow-x-auto">
                            <code>{msg.lua_code}</code>
                        </pre>
                    )}
                </div>
            ))}
            {sending && !optimisticMsg && <LoadingAnimation />}
            {sending && optimisticMsg && (
                <div className="self-start">
                    <LoadingAnimation />
                </div>
            )}
            <div ref={bottomRef} />
        </div>
    )
}
