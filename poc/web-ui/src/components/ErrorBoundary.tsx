// Barrière d'erreur : une donnée inattendue dans une vue affiche un message et le reste de l'interface
// (barre du haut, autres vues) continue de marcher, au lieu d'une page blanche.
import { Component, type ReactNode } from "react";

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section className="card" role="alert">
        <h2>Cet écran n'a pas pu s'afficher</h2>
        <p className="muted">
          Une donnée reçue n'a pas la forme attendue : {this.state.error.message}. Les autres écrans restent utilisables
          ; recharge la page ou reviens à l'accueil.
        </p>
        <p>
          <a href="#">← Accueil</a>
        </p>
      </section>
    );
  }
}
