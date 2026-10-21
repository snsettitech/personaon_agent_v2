'use client';

import { driver, type DriveStep, type Driver } from 'driver.js';
import React, { useCallback, useEffect, useRef, useState } from 'react';

import { analytics, type DashboardWalkthroughSurface } from '@/lib/analytics/events';
import { useTwin } from '@/lib/context/TwinContext';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

interface WalkthroughStep {
  id: string;
  title: string;
  description: string;
}

const DESKTOP_STEPS: WalkthroughStep[] = [
  { id: 'home', title: 'Home', description: 'Your command center for status and next best actions.' },
  { id: 'build', title: 'Build', description: 'Shape the profile, knowledge, and studio setup.' },
  { id: 'chat', title: 'Chat', description: 'Test answers and review real conversations.' },
  { id: 'meetings', title: 'Meet', description: 'Manage bookings and meeting room activity.' },
  { id: 'publish', title: 'Publish', description: 'Share your persona through links and widgets.' },
  { id: 'control', title: 'Control', description: 'Review insights, responses, billing, and settings.' },
];

const MOBILE_STEPS = DESKTOP_STEPS.filter((step) => step.id !== 'control');

const COMPLETE_ENDPOINT = '/auth/dashboard-walkthrough/complete';
const STATUS_ENDPOINT = '/auth/dashboard-walkthrough';

function getSurface(): DashboardWalkthroughSurface {
  return window.matchMedia('(max-width: 767px)').matches ? 'mobile_tabbar' : 'desktop_sidebar';
}

function selectorFor(step: WalkthroughStep): string {
  return `[data-tour-id="dashboard-nav-${step.id}"]`;
}

function getAvailableSteps(surface: DashboardWalkthroughSurface): WalkthroughStep[] {
  const steps = surface === 'mobile_tabbar' ? MOBILE_STEPS : DESKTOP_STEPS;
  return steps.filter((step) => document.querySelector(selectorFor(step)));
}

async function fetchWalkthroughCompleted(): Promise<boolean> {
  const response = await authFetchStandalone(STATUS_ENDPOINT);
  if (!response.ok) return true;
  const body = await response.json().catch(() => ({}));
  return Boolean(body?.completed_at);
}

async function persistWalkthroughCompleted(): Promise<void> {
  try {
    const response = await authFetchStandalone(COMPLETE_ENDPOINT, { method: 'POST' });
    if (!response.ok) {
      console.error('[DashboardWalkthrough] failed to persist completion', response.status);
    }
  } catch (error) {
    console.error('[DashboardWalkthrough] failed to persist completion', error);
  }
}

export default function DashboardWalkthrough(): React.JSX.Element | null {
  const { activeTwin, isLoading, twins } = useTwin();
  const [shouldStart, setShouldStart] = useState(false);
  const driverRef = useRef<Driver | null>(null);
  const hasStartedRef = useRef(false);
  const completedRef = useRef(false);
  const currentStepRef = useRef(0);
  const surfaceRef = useRef<DashboardWalkthroughSurface>('desktop_sidebar');
  const stepsRef = useRef<WalkthroughStep[]>([]);

  const twinId = activeTwin?.id;

  const commonProps = useCallback(() => ({
    surface: surfaceRef.current,
    twin_id: twinId,
  }), [twinId]);

  const markCompleted = useCallback(() => {
    if (completedRef.current) return;
    completedRef.current = true;
    void persistWalkthroughCompleted();
  }, []);

  const captureStepViewed = useCallback((stepIndex: number) => {
    const step = stepsRef.current[stepIndex];
    if (!step) return;
    currentStepRef.current = stepIndex;
    analytics.dashboardWalkthroughStepViewed({
      ...commonProps(),
      step_id: step.id,
      step_index: stepIndex,
      step_count: stepsRef.current.length,
    });
  }, [commonProps]);

  const buildDriveSteps = useCallback((steps: WalkthroughStep[]): DriveStep[] => (
    steps.map((step, index) => ({
      element: selectorFor(step),
      popover: {
        title: step.title,
        description: step.description,
        side: surfaceRef.current === 'mobile_tabbar' ? 'top' : 'right',
        align: 'center',
        onNextClick: (_element, _step, { driver: activeDriver }) => {
          if (index === stepsRef.current.length - 1) {
            markCompleted();
            analytics.dashboardWalkthroughCompleted({
              ...commonProps(),
              step_count: stepsRef.current.length,
            });
            activeDriver.destroy();
            return;
          }
          activeDriver.moveNext();
        },
        onPrevClick: (_element, _step, { driver: activeDriver }) => {
          activeDriver.movePrevious();
        },
        onCloseClick: (_element, _step, { driver: activeDriver }) => {
          markCompleted();
          analytics.dashboardWalkthroughSkipped({
            ...commonProps(),
            step_id: step.id,
            step_index: index,
            step_count: stepsRef.current.length,
          });
          activeDriver.destroy();
        },
      },
      onHighlighted: () => captureStepViewed(index),
    }))
  ), [captureStepViewed, commonProps, markCompleted]);

  useEffect(() => {
    // The tour is intentionally delayed until a user has created their first twin,
    // so the dashboard navigation points at real sections rather than an empty shell.
    if (isLoading || twins.length === 0) return;
    let cancelled = false;

    const timer = window.setTimeout(() => {
      void (async () => {
        const completed = await fetchWalkthroughCompleted();
        if (!cancelled && !completed) {
          setShouldStart(true);
        }
      })();
    }, 500);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [isLoading, twins.length]);

  useEffect(() => {
    if (!shouldStart || hasStartedRef.current) return;

    const surface = getSurface();
    const steps = getAvailableSteps(surface);
    if (steps.length === 0) return;

    surfaceRef.current = surface;
    stepsRef.current = steps;
    hasStartedRef.current = true;

    analytics.dashboardWalkthroughStarted({
      ...commonProps(),
      step_count: steps.length,
    });

    const tour = driver({
      steps: buildDriveSteps(steps),
      allowClose: true,
      animate: true,
      disableActiveInteraction: true,
      overlayColor: '#1d1d1f',
      overlayOpacity: 0.42,
      popoverClass: 'personaon-dashboard-walkthrough',
      popoverOffset: 14,
      showButtons: ['previous', 'next', 'close'],
      showProgress: true,
      stagePadding: 6,
      stageRadius: 24,
      nextBtnText: 'Next',
      prevBtnText: 'Back',
      doneBtnText: 'Done',
      progressText: '{{current}}/{{total}}',
      onPopoverRender: (popover) => {
        popover.closeButton.textContent = '×';
        popover.closeButton.setAttribute('aria-label', 'Skip dashboard walkthrough');
      },
      onDestroyStarted: (_element, _step, { driver: activeDriver }) => {
        if (!completedRef.current) {
          const index = currentStepRef.current;
          const step = stepsRef.current[index] ?? stepsRef.current[0];
          markCompleted();
          analytics.dashboardWalkthroughSkipped({
            ...commonProps(),
            step_id: step.id,
            step_index: index,
            step_count: stepsRef.current.length,
          });
        }
        activeDriver.destroy();
      },
    });

    driverRef.current = tour;
    tour.drive();

    return () => {
      if (driverRef.current?.isActive()) {
        completedRef.current = true;
        driverRef.current.destroy();
      }
      driverRef.current = null;
    };
  }, [buildDriveSteps, commonProps, markCompleted, shouldStart]);

  return null;
}
