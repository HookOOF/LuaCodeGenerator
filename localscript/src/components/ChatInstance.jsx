export default function ChatInstance({ id, title, isActive, onClick }) {
    return (
        <button
            onClick={onClick}
            className={`flex justify-center items-center w-full
                h-4 p-5 rounded-[7px] cursor-pointer
                ${isActive ? 'backdrop-brightness-250' : 'backdrop-brightness-200 hover:backdrop-brightness-175'}`}
        >
            <h4 className="truncate w-full text-left">{title}</h4>
        </button>
    )
}
