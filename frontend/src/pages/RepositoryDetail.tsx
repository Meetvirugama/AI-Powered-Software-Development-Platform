import { useParams, Link } from 'react-router-dom';

export function RepositoryDetail() {
  const { id } = useParams();

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Repository Detail: {id}</h1>
      <div className="flex space-x-4">
        <Link to={`/app/repositories/${id}/chat`} className="px-4 py-2 bg-primary text-primary-foreground rounded-lg">
          Open Chat
        </Link>
      </div>
      <p className="text-muted-foreground">
        Repository metrics, PRs, and execution tasks will appear here.
      </p>
    </div>
  );
}
