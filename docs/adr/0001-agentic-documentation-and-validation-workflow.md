# Documentation agentique et workflow de validation

Status: accepted

Le projet utilise `docs/AGENT_CONTEXT.md` comme reference principale pour les agents, avec `docs/MVP.md`, `docs/ARCHITECTURE.md`, `GLOSSARY.md` et `docs/adr/` comme documents de support. Toute phase majeure d'implementation doit suivre le workflow Research puis ADR puis validation utilisateur, afin d'eviter que les agents reinterpretent le cahier des charges ou figent des choix techniques sans controle humain.

## Consequences

- Les agents doivent lire le contexte avant de coder.
- Les decisions structurantes sont documentees avant implementation.
- La vitesse brute est sacrifiee lorsque necessaire pour proteger la coherence du POC.
