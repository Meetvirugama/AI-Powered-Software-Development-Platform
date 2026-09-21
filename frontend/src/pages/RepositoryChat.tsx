import { useParams } from 'react-router-dom';

export function RepositoryChat() {
  const { id } = useParams();

  return (
    <div className="flex flex-col h-full space-y-4">
      <h1 className="text-2xl font-bold">Repository Chat: {id}</h1>
      <div className="flex-1 p-4 border rounded-lg overflow-auto bg-card">
        <p className="text-muted-foreground">Chat messages will appear here.</p>
      </div>
      <div className="flex space-x-2">
        <input
          type="text"
          placeholder="Ask a question about the repository..."
          className="flex-1 p-2 border rounded-lg"
        />
        <button className="px-4 py-2 bg-primary text-primary-foreground rounded-lg">
          Send
        </button>
      </div>
    </div>
  );
}
