import { Component, HostListener, inject, signal, viewChild } from '@angular/core';
import type { Dests } from '@lichess-org/chessground/types';

import { AnalysisPanelComponent } from './analysis-panel/analysis-panel';
import { ChessboardComponent } from './chessboard/chessboard';
import { LevelSelectorComponent } from './level-selector/level-selector';
import { AnalyzePositionResponse, PedagogicalLevel } from './models/analysis';
import { BoardMove } from './models/game';
import { MoveHistoryComponent } from './move-history/move-history';
import { AnalysisService } from './services/analysis';
import { GameSnapshot, GameStateService } from './services/game-state';

@Component({
  selector: 'app-root',
  imports: [
    AnalysisPanelComponent,
    ChessboardComponent,
    LevelSelectorComponent,
    MoveHistoryComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  readonly ratingBuckets = [0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500];
  private readonly analysisService = inject(AnalysisService);
  private readonly gameState = inject(GameStateService);
  private readonly board = viewChild(ChessboardComponent);
  private readonly initialGameState = this.gameState.snapshot();

  readonly level = signal<PedagogicalLevel>('debutant');
  readonly ratingMin = signal(1000);
  readonly ratingMax = signal(1400);
  readonly fen = signal(this.initialGameState.fen);
  readonly legalDests = signal<Dests>(this.initialGameState.legalDests);
  readonly pgn = signal('');
  readonly moves = signal<string[]>([]);
  readonly line = signal<string[]>([]);
  readonly currentIndex = signal(0);
  readonly totalMoves = signal(0);
  readonly analysis = signal<AnalyzePositionResponse | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly sessionId = signal<string | null>(null);

  private readonly analysisCache = new Map<string, AnalyzePositionResponse>();

  setLevel(level: PedagogicalLevel): void {
    this.level.set(level);
    this.applyRatingPreset(level);
    this.refreshAnalysis();
  }

  setRatingMin(value: string | number): void {
    const rating = Number(value);
    this.ratingMin.set(rating);
    if (rating > this.ratingMax()) {
      this.ratingMax.set(rating);
    }
    this.refreshAnalysis();
  }

  setRatingMax(value: string | number): void {
    const rating = Number(value);
    this.ratingMax.set(rating);
    if (rating < this.ratingMin()) {
      this.ratingMin.set(rating);
    }
    this.refreshAnalysis();
  }

  reset(): void {
    this.syncGameState(this.gameState.reset());
    this.analysis.set(null);
    this.error.set(null);
    this.sessionId.set(null);
  }

  playDemoMove(): void {
    this.reset();
    this.applyMove({ from: 'e2', to: 'e4' });
  }

  onMoveRequested(move: BoardMove): void {
    this.applyMove(move);
  }

  goBack(): void {
    this.navigate(() => this.gameState.goBack());
  }

  goForward(): void {
    this.navigate(() => this.gameState.goForward());
  }

  @HostListener('document:keydown', ['$event'])
  onKeydown(event: KeyboardEvent): void {
    if (this.isFormTarget(event.target)) {
      return;
    }
    if (event.key === 'ArrowLeft' && this.currentIndex() > 0) {
      event.preventDefault();
      this.goBack();
    } else if (event.key === 'ArrowRight' && this.currentIndex() < this.totalMoves()) {
      event.preventDefault();
      this.goForward();
    }
  }

  private navigate(navigate: () => GameSnapshot | null): void {
    const snapshot = navigate();
    if (!snapshot) {
      return;
    }
    this.syncGameState(snapshot);
    if (snapshot.currentIndex === 0) {
      this.analysis.set(null);
      return;
    }
    this.showAnalysis();
  }

  private applyMove(move: BoardMove): void {
    const result = this.gameState.applyMove(move);

    this.syncGameState(result.snapshot);

    if (result.ok) {
      this.showAnalysis();
      return;
    }

    this.error.set('Coup illegal pour la position courante.');
  }

  private refreshAnalysis(): void {
    if (this.currentIndex() === 0) {
      this.analysis.set(null);
      return;
    }
    this.showAnalysis();
  }

  private showAnalysis(): void {
    const cached = this.analysisCache.get(this.positionKey());
    if (cached) {
      this.analysis.set(cached);
      this.error.set(null);
      return;
    }
    this.analyze();
  }

  private analyze(): void {
    this.loading.set(true);
    this.error.set(null);

    this.analysisService
      .analyzePosition({
        fen: this.fen(),
        pgn: this.pgn() || 'Position initiale',
        moves: this.moves(),
        level: this.level(),
        rating_min: this.ratingMin(),
        rating_max: this.ratingMax(),
        session_id: this.sessionId(),
      })
      .subscribe({
        next: (analysis) => {
          this.analysisCache.set(this.positionKey(), analysis);
          this.analysis.set(analysis);
          this.sessionId.set(analysis.session_id ?? null);
          this.loading.set(false);
        },
        error: () => {
          this.error.set('Analyse indisponible. Verifie que le backend FastAPI est lance.');
          this.loading.set(false);
        },
      });
  }

  private positionKey(): string {
    return [this.fen(), this.level(), this.ratingMin(), this.ratingMax()].join('|');
  }

  private syncGameState(state: GameSnapshot): void {
    this.fen.set(state.fen);
    this.legalDests.set(state.legalDests);
    this.pgn.set(state.pgn);
    this.moves.set(state.moves);
    this.line.set(state.line);
    this.currentIndex.set(state.currentIndex);
    this.totalMoves.set(state.totalMoves);
    this.syncBoardPosition(state);
  }

  private syncBoardPosition(state: GameSnapshot): void {
    this.board()?.setPosition(
      state.fen,
      state.turn,
      state.legalDests,
    );
  }

  private applyRatingPreset(level: PedagogicalLevel): void {
    const presets: Record<PedagogicalLevel, { min: number; max: number }> = {
      debutant: { min: 1000, max: 1400 },
      intermediaire: { min: 1600, max: 2000 },
      avance: { min: 2200, max: 2500 },
    };
    this.ratingMin.set(presets[level].min);
    this.ratingMax.set(presets[level].max);
  }

  private isFormTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) {
      return false;
    }
    const tag = target.tagName.toLowerCase();
    return (
      tag === 'input' ||
      tag === 'textarea' ||
      tag === 'select' ||
      tag === 'button' ||
      target.isContentEditable
    );
  }
}
