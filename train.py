import pickle
import time
from torch.multiprocessing import Manager, Queue
from torch.utils.tensorboard import SummaryWriter

from config import OthelloConfig
from utils.util import ReplayBuffer
from utils.workers import SelfPlayWorker, TrainingWorker, EvaluationWorker


def train(experiment: int, batch: int, resume: bool):
    cfg = OthelloConfig(experiment, batch)
    manager = Manager()
    buffer = manager.list()
    replay_buffer = ReplayBuffer(buffer)
    shared_state_dicts = manager.dict()
    message_queue = Queue()
    log_queue = Queue()  # a single log is dictionary and "gs", "type" keys are must
    writer = SummaryWriter(cfg.dir_log)
    if resume:
        print("Loading replay buffer to resume training...")
        with open(cfg.dir_replay_buffer, "rb") as f:
            buff_list = pickle.load(f)
        replay_buffer.save_training_data(buff_list)
        del buff_list
        print("Replay buffer loaded.")
    training_worker = TrainingWorker(
        "Training Worker", message_queue, log_queue, shared_state_dicts, replay_buffer, cfg.device_name_tw, cfg, resume
    )
    evaluation_worker = EvaluationWorker(
        "Evaluation Worker", message_queue, log_queue, shared_state_dicts, cfg.device_name_ew, cfg, resume
    )
    self_play_workers = []
    for i in range(cfg.num_self_play_workers):
        self_play_workers.append(SelfPlayWorker("Self-Play Worker-" + str(i), message_queue, log_queue,
                                                shared_state_dicts, replay_buffer, cfg.device_names_sp[i], cfg))
    print("Starting training...")
    training_worker.start()
    evaluation_worker.start()
    for worker in self_play_workers:
        worker.start()
    print("Training started.")
    try:
        while training_worker.is_alive():
            if log_queue.empty():
                time.sleep(1.0)
                continue
            log = log_queue.get()
            for k, v in log.items():
                if k in ["gs", "type"]:
                    continue
                if log["type"] == "scalar":
                    writer.add_scalar(k, v, log["gs"])
                else:
                    print("Unknown log type found:", log["type"])
            del log
    except KeyboardInterrupt:
        print("KeyboardInterrupt, stopping training...")
    finally:
        for i in range(cfg.num_self_play_workers * 5):
            message_queue.put(cfg.message_interrupt)
        training_worker.join()
        evaluation_worker.join()
        for worker in self_play_workers:
            worker.join()
        print("Saving replay buffer...")
        buff_list = list(buffer)
        with open(cfg.dir_replay_buffer, "wb") as f:
            pickle.dump(buff_list, f)
        del buff_list
        print("Replay buffer saved.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=int, required=True)
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--resume", type=bool, default=False)
    args = parser.parse_args()
    train(args.experiment, args.batch, args.resume)
