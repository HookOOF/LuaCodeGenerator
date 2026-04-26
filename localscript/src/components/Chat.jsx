import { Send } from 'lucide-react';
import { useState, useRef } from 'react';
import { createSession, sendMessage } from '../api';
import ChatMessages from './ChatMessages';

export default function Chat({ sessionId, onSessionCreated }) {
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [optimisticMsg, setOptimisticMsg] = useState(null);
    const [refreshMessages, setRefreshMessages] = useState(0);
    const textareaRef = useRef(null);

    const handleSend = async () => {
        const text = input.trim();
        if (!text || sending) return;

        setSending(true);
        setInput('');
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
        }

        try {
            let sid = sessionId;
            if (!sid) {
                const session = await createSession();
                sid = session.id;
                onSessionCreated(sid);
            }

            setOptimisticMsg({ role: 'user', content: text });
            await sendMessage(sid, text);
            setOptimisticMsg(null);
            setRefreshMessages((k) => k + 1);
        } catch (err) {
            console.error(err);
            setOptimisticMsg(null);
        } finally {
            setSending(false);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="flex flex-col h-screen w-full items-end">
            <div className="flex flex-1 max-h-[90vh] w-full justify-center overflow-hidden">
                {sessionId
                    ? <ChatMessages sessionId={sessionId} refreshKey={refreshMessages} optimisticMsg={optimisticMsg} sending={sending} />
                    : <div className="flex items-center justify-center w-full text-center text-5xl text-neutral-600 select-none">New Chat...</div>
                }
            </div>
            <div className="w-full items-end">
                <div className="flex flex-row w-full items-center mx-auto p-10">
                    <textarea
                        ref={textareaRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="I code in Lua :3"
                        className="flex-1 text-xl bg-neutral-800 rounded-[25px] p-4 pl-8
                           resize-none overflow-y-auto max-h-[10vh]
                           outline-none focus:ring-neutral-700 focus:ring-2
                           [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
                        rows={1}
                        onKeyDown={handleKeyDown}
                        onInput={(e) => {
                            e.target.style.height = 'auto';
                            e.target.style.height = e.target.scrollHeight + 'px';
                        }}
                    />
                    <div className="ml-2">
                        <button
                            onClick={handleSend}
                            disabled={sending || !input.trim()}
                            className="bg-neutral-800 p-4 rounded-full
                                hover:bg-neutral-700 transition
                                disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                        >
                            <Send size={24} className="text-amber-50" />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    )
}
