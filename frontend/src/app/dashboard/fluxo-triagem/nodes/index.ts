import StartNode from "./StartNode";
import EndNode from "./EndNode";
import LoopNode from "./LoopNode";
import SendTextNode from "./SendTextNode";
import SendMenuNode from "./SendMenuNode";
import SendImageNode from "./SendImageNode";
import SendAudioNode from "./SendAudioNode";
import AIRespondNode from "./AIRespondNode";
import AIClassifyNode from "./AIClassifyNode";
import AISentimentNode from "./AISentimentNode";
import AIQualifyNode from "./AIQualifyNode";
import AIExtractNode from "./AIExtractNode";
import SwitchNode from "./SwitchNode";
import ConditionNode from "./ConditionNode";
import DelayNode from "./DelayNode";
import WaitInputNode from "./WaitInputNode";
import HumanTransferNode from "./HumanTransferNode";
import WebhookNode from "./WebhookNode";

export const nodeTypes = {
  start:         StartNode,
  end:           EndNode,
  loop:          LoopNode,
  sendText:      SendTextNode,
  sendMenu:      SendMenuNode,
  sendImage:     SendImageNode,
  sendAudio:     SendAudioNode,
  aiRespond:     AIRespondNode,
  aiClassify:    AIClassifyNode,
  aiSentiment:   AISentimentNode,
  aiQualify:     AIQualifyNode,
  aiExtract:     AIExtractNode,
  switch:        SwitchNode,
  condition:     ConditionNode,
  delay:         DelayNode,
  waitInput:     WaitInputNode,
  humanTransfer: HumanTransferNode,
  webhook:       WebhookNode,
};
