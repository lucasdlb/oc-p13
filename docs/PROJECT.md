> Statut documentaire : brief client brut.
>
> Ce fichier conserve la demande initiale et les contraintes externes historiques. Il ne doit pas etre maintenu comme specification vivante. Pour travailler sur le projet, utiliser d'abord `docs/AGENT_CONTEXT.md`, puis les documents specialises qu'il reference.

**Contexte**: La FFE est l’organisation officielle chargée de promouvoir et développer le jeu d’échecs en France. En vue des futurs championnats d’Europe jeune, elle souhaite proposer un agent intelligent capable d’accompagner les jeunes espoirs dans l’apprentissage des ouvertures aux échecs.

**Role**: Je suis IA Engineer junior, ce projet s'inscrit dans le cadre d'une mission pour le compte de la Fédération Française des Échecs (FFE). Je suis chargé de développer un POC (Proof of Concept) de cet agent en 2 semaines.

**Cahier des charges**: L’agent IA devra guider les jeunes espoirs en :

 + leur proposant les meilleurs coups issus de la théorie, 
 + le contexte des ouvertures via des données enrichies par les parties historiques, 
 + des vidéos explicatives pertinentes, 
 + et une évaluation de la position par un moteur spécialisé (exemple Stockfish) si la partie s’écarte des sentiers battus.


**Objectif de la mission**: développer, une première version fonctionnelle qui :
+ Propose une interface Angular avec échiquier interactif (ngx-chessboard) :
    + https://github.com/OpenClassrooms-Student-Center/material-chessboard
+ Guide l’utilisateur grâce à un agent IA connecté à :
    + une identification de la position en cours par identifiant fen https://www.chess.com/terms/fen-chess.
    + un Stockfish (moteur d’échecs spécialisé), https://pypi.org/project/stockfish/
    + des APIs Lichess (bibliothèque d’ouvertures et parties de références). https://lichess.org/api#description/introduction
    + une intégration des données issues de Wikichess dans une base Milvus  pour la recherche vectorielle (toutes sources pertinentes sont acceptées) https://ficgs.com/wikichess_1.html
    + un affichage de vidéos explicatives YouTube pertinentes (relatives à la position en cours) grâce à youtube api. 

**Livrables attendus** :

+ Système développé avec Lang Graph, Fastapi, Milvus et Mongodb.
+ Code accessible via un dépôt Git
+ Démonstration de l’Agent IA au client (exécution locale avec docker compose).


## Livrables
 + Système développé avec Lang Graph, Fastapi, Milvus et Mongodb.
    + Code accessible via un dépôt Git 
    + Démonstration de l’Agent IA au client, exécution locale avec docker compose.

 + Note détaillée sur les bénéfices et limites du système incluant :
    + un schéma d'architecture technique, 
    + une étude de faisabilité avec estimation des coûts. 















