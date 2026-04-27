from core.config import provider_key_model_semaphores, provider_key_semaphores

print("Provider key model semaphores:")
for k, v in provider_key_model_semaphores.items():
    limit = getattr(v, "_modelgate_scoped_limit", "?")
    waiters = len(v._waiters) if v._waiters else 0
    print(f"  {k}: value={v._value}, limit={limit}, waiters={waiters}")

print("\nProvider key semaphores:")
for k, v in provider_key_semaphores.items():
    limit = getattr(v, "_modelgate_scoped_limit", "?")
    waiters = len(v._waiters) if v._waiters else 0
    print(f"  {k}: value={v._value}, limit={limit}, waiters={waiters}")
