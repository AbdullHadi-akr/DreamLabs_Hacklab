"""Prueft, ob alles fuer die Arbeit bereit ist.

    python check_setup.py            # offline: Python, Pakete, Simulator, Kameras, Credentials
    python check_setup.py --online   # zusaetzlich: API-Key gegen DreamAPI pruefen (listet deine Modelle)
"""

import argparse
import sys

OK, FAIL, WARN = "[ OK ]", "[FAIL]", "[WARN]"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    failed = False

    v = sys.version_info
    good = (3, 11) <= (v.major, v.minor) < (3, 14)
    print(OK if good else FAIL, f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    failed |= not good

    try:
        import dream
        import mujoco

        print(OK, f"dreamlabs-client {dream.__version__}, mujoco {mujoco.__version__}")
    except ImportError as error:
        print(FAIL, f"Paket fehlt: {error}. Siehe README -> Setup.")
        return 1

    try:
        from dreamtool import scene, sim

        print(OK, f"Simulator gefunden: {sim.SIM_DIR}")
        env = sim.YamEnv()
        for _ in range(10):
            env.step(sim.HOME, sim.HOME)
        images = env.images()
        shapes = {k: v.shape for k, v in images.items()}
        print(OK, f"Physik + Rendering laufen: {shapes}")
        print(OK, f"Objekte: {', '.join(f'{k}@{v.round(2).tolist()}' for k, v in scene.positions(env).items())}")
        env.close()
    except Exception as error:
        print(FAIL, f"Simulator: {type(error).__name__}: {error}")
        failed = True

    config = sim.settings()
    key = config.get("DREAM_API_KEY", "")
    if key:
        print(OK, f"API-Key gefunden: {key[:8]}...{key[-4:]}  Gateway: {config.get('DREAM_GATEWAY_URL', 'default')}")
    else:
        print(WARN, "Kein API-Key. Offline-Arbeit geht, fuer Dream-1 siehe README -> API-Key.")

    if args.online and key:
        try:
            with dream.DreamClient(api_key=key) as client:
                models = client.get_models()
            print(OK, f"DreamAPI erreichbar, {len(models)} Modell(e): {', '.join(str(getattr(m, 'id', m)) for m in models[:5])}")
        except Exception as error:
            print(FAIL, f"DreamAPI: {type(error).__name__}: {error}")
            failed = True

    print("\nAlles bereit." if not failed else "\nEs gibt Probleme (siehe [FAIL]).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
