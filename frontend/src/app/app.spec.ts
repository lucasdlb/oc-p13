import { TestBed } from '@angular/core/testing';
import { App } from './app';
import { provideHttpClient } from '@angular/common/http';
import { of } from 'rxjs';

import { AnalyzePositionResponse } from './models/analysis';
import { AnalysisService } from './services/analysis';

function analysisStub(sessionId: string): AnalyzePositionResponse {
  return {
    opening: {
      eco: 'B00',
      name: "King's Pawn Game",
      matched: true,
      source: 'demo-opening-seed',
    },
    recommended_moves: [],
    masters_moves: [],
    masters_stats: { source: 'masters-opening-explorer', games: 0, white: 0, draws: 0, black: 0 },
    lichess_stats: {},
    source_confidence: {},
    rag_context: [],
    coach_explanation: 'demo',
    stockfish: null,
    videos: [],
    fallbacks_used: [],
    session_id: sessionId,
    cache: {},
  };
}

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideHttpClient(),
        {
          provide: AnalysisService,
          useValue: { analyzePosition: () => of(analysisStub('session-1')) },
        },
      ],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render the opening coach shell', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toContain("Analyse d'ouverture");
  });

  it('navigates the timeline with keyboard arrows', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    app.onMoveRequested({ from: 'e7', to: 'e5' });

    expect(app.currentIndex()).toBe(2);
    expect(app.totalMoves()).toBe(2);
    expect(app.sessionId()).toBe('session-1');

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));

    expect(app.currentIndex()).toBe(1);
    expect(app.moves()).toEqual(['e2e4']);
    expect(app.analysis()).not.toBeNull();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));

    expect(app.currentIndex()).toBe(0);
    expect(app.analysis()).toBeNull();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));

    expect(app.currentIndex()).toBe(0);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));

    expect(app.currentIndex()).toBe(1);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));

    expect(app.currentIndex()).toBe(2);
    expect(app.moves()).toEqual(['e2e4', 'e7e5']);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));

    expect(app.currentIndex()).toBe(2);
  });

  it('ignores keyboard navigation while focus is in a form control', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });

    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    input.remove();

    expect(app.currentIndex()).toBe(1);
  });

  it('reset clears the local timeline and session without a network call', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });

    expect(app.sessionId()).toBe('session-1');

    app.reset();

    expect(app.sessionId()).toBeNull();
    expect(app.currentIndex()).toBe(0);
    expect(app.totalMoves()).toBe(0);
    expect(app.moves()).toEqual([]);
    expect(app.analysis()).toBeNull();
    expect(app.error()).toBeNull();
  });

  it('restores a cached analysis when navigating back to an analyzed position', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    app.onMoveRequested({ from: 'e7', to: 'e5' });
    app.goBack();

    expect(app.analysis()).not.toBeNull();
    expect(app.analysis()!.session_id).toBe('session-1');
  });
});
