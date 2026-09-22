import { Link } from 'react-router-dom';

export function Repositories() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Repositories</h1>
      <p className="text-muted-foreground">
        List of connected GitHub repositories.
      </p>
      <ul className="space-y-2">
        <li>
          <Link to="/app/repositories/1" className="text-primary hover:underline">
            Repository 1
          </Link>
        </li>
      </ul>
    </div>
  );
}
