"""API CLI 入口: python -m valhalla.api --mid 322005137"""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Valhalla API 服务")
    parser.add_argument("--mid", type=int, default=322005137)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    from valhalla.api.main import create_app
    import uvicorn

    app = create_app(args.mid)
    print(f"\n  Valhalla API: http://{args.host}:{args.port}")
    print(f"  API 文档:     http://{args.host}:{args.port}/docs\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
