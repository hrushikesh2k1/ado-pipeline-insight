import sys
sys.path.insert(0, ".")
import json
from backend.app.services.ai_service import AIService

def main():
    ai = AIService()
    result = ai.analyze(pipeline_id=1, days=90)
    print("AI Analysis Result:")
    print(json.dumps(result, indent=2))
    for f in result.get("findings", []):
        print(f"\nFinding Category: {f.get('category')}")
        print(f"Task: {f.get('task_name')}")
        print(f"Recommendation: {f.get('recommendation')}")
        print(f"Evidence: {f.get('evidence')}")
        assert "318" not in f.get("evidence", ""), "318% must not appear in evidence!"
        assert "318" not in f.get("recommendation", ""), "318% must not appear in recommendation!"
    print("\nSTEP 12 LOCAL AI TEST PASSED!")

if __name__ == '__main__':
    main()
