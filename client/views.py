from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpRequest
from django.views.generic import ListView, View
import pandas as pd
from .models import Client, Marketing
from .forms import ClientForm  # 고객 모델 폼
from django.urls import reverse
from datetime import datetime
import os
import zipfile
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from account.models import CompanyFile
from pytz import UTC
from django.core.paginator import Paginator

from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQAWithSourcesChain
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import Chroma

open_api_key = os.environ.get('OPENAI_API_KEY')

class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = 'client/client_list.html'  
    
    def get_context_data(self, **kwargs): # 2
        context = super().get_context_data(**kwargs)  # 컨텍스트 데이터 가져옴
        
        client_list = Client.objects.filter(user = self.request.user)
        file_list = CompanyFile.objects.filter(user = self.request.user)

        client_paginator = Paginator(client_list, 5)
        file_paginator = Paginator(file_list, 5)
    
        client_page_number = self.request.GET.get('client_page')
        file_page_number = self.request.GET.get('file_page')
        
            
        client_obj = client_paginator.get_page(client_page_number)
        file_obj = file_paginator.get_page(file_page_number)
        
        
        context['tmgoal'] = self.request.session.get('tmgoal', None)
        context['client_obj'] = client_obj
        context['file_obj'] = file_obj

        return context

    def post(self, request, *args, **kwargs):
        selected_ids = request.POST.getlist('client_ids')  
        Client.objects.filter(id__in=selected_ids).delete()  
        return redirect(reverse('client:list'))  
    
    def get_queryset(self): 
        user = self.request.user
        print(f"Current User ID: {user.id}")
        queryset = Client.objects.filter(user=self.request.user).order_by('-tm_date')  # '-tm_date'는 내림차순 정렬을 의미
        print(f"Queryset length: {queryset.count()}")
        #print(f"Queryset data: {queryset.values()}")
        return queryset



class DeleteSelectedClientsView(View):
    def post(self, request):
        selected_ids = request.POST.getlist('client_ids')  
        Client.objects.filter(id__in=selected_ids).delete()  
        return redirect(reverse('client:list'))  


def normalize_gender(gender_str):
    # 성별을 Male, Female로 변환
    
    if gender_str in ['남성', '남', '남자', 'm', 'M']:
        return '남'
    elif gender_str in ['여성', '여', '여자', 'f', 'F']:
        return '여'
    else:
        return None  
    

    
def upload_excel(request): # 이상 없음.
    if request.method == 'POST':
        excel_file = request.FILES['excel_file']
        tmgoal = request.POST.get('tmgoal')
        request.session['tmgoal'] = tmgoal
        df = pd.read_excel(excel_file)
        
        print(df.columns)

        for index, row in df.iterrows():
            user = request.user
            name = str(row['name'])
            number = row['number']
            email = row['email']
            print(name, number, email)
            # 기존에 손님 데이터와 중복되는 데이터인지 확인
            existing_client = Client.objects.filter(name=name, number=number, email=email, user= user).first()
            
            if existing_client is not None:
                print(existing_client.name)
                continue
            
            # raw_birth_date 에는 마스킹 전 생년월일
            raw_birth_date = row.get('birth_date', None)
            
            # 생년월일이 엑셀로 들어올 경우, age 계산
            if raw_birth_date:
                birth_date = raw_birth_date.to_pydatetime()  # Timestamp 객체를 datetime 객체로 변환
                today = datetime.today()
                age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            
                # 생년월일 마스킹        
                masked_birth_date = raw_birth_date.strftime('%Y-%m-%d')[:5] + 'XX-XX'
            else:  
                age = None
                masked_birth_date = None
            
            # 정규화 전 성별
            raw_gender = row.get('gender', None)
            
            # 성별 변환
            normalized_gender = normalize_gender(raw_gender)
            
            temp_date = UTC.localize(datetime.now())
            
            user = request.user # 문제는 원래 저장되어 있던 데이터여서 새로 안된거일 뿐이었다. 데이터베이스를 초기화하는 코드가 약간 필요할듯 하다.
            #if user.is_authenticated:
            #    print(f"User ID: {user.pk}")
            #else:
            #    print("User is not authenticated.")
            
            Client.objects.create(
                user=user,
                name=name,
                location=row['location'],
                number=number,
                birth_date=masked_birth_date,
                age=age,
                tm_date=temp_date,
                gender=normalized_gender,
                email=email,
            )
        print(f"Client {Client.id} created successfully.")  # 디버깅 메시지 잘뜬다.
        print(tmgoal)
        
        return redirect('client:list')
    
    
    return render(request, 'client/upload.html')


def edit_client(request, client_id):
    client = get_object_or_404(Client, id=client_id, user=request.user)
    
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            return redirect('client:list')  # 클라이언트 목록 뷰로 리디렉션
    else:
        form = ClientForm(instance=client)
    
    return render(request, 'client/edit_client.html', {'form': form, 'client': client})

@login_required
def delete_client(request, client_id):
    client = get_object_or_404(Client, id=client_id, user=request.user)
    
    if request.method == 'POST':
        client.delete()
        return redirect('client:list')  # 클라이언트 목록 뷰로 리디렉션
    
    return render(request, 'client/delete_client.html', {'client': client})


def selected_items(request):
    selected_clients = request.GET.get('selected_clients', '').split(',')
    selected_files = request.GET.get('selected_files', '').split(',')

    # 빈 문자열을 제거합니다. ( 선택이 안된 경우 )
    selected_clients = [id for id in selected_clients if id]
    selected_files = [id for id in selected_files if id]

    # 처음엔 빈 쿼리셋할당
    clients = Client.objects.none()  
    files = CompanyFile.objects.none()  

    if selected_clients:   # 해당 되는 clients 넣어줌
        clients = Client.objects.filter(id__in=selected_clients)

    if selected_files:     # 해당 되는 files 넣어줌
        files = CompanyFile.objects.filter(id__in=selected_files)
        

    context = {
        'selectedClients': clients,
        'selectedFiles': files,
    }

    return render(request, 'client/selected_items.html', context)

def start_tm(request):
    input_data = ''
    selected_clients = []
    selected_files = []

    if request.method == 'POST':
        input_data = request.POST.get('input_data', '') # query
        selected_clients = request.POST.getlist('client_ids')
        selected_files = request.POST.getlist('file_ids')
        llm = ChatOpenAI(model_name="gpt-3.5-turbo-16k", temperature=0, openai_api_key=open_api_key )
        
        system_template = """다음과 같은 맥락을 사용하여 마지막 질문에 대답하십시오.
        만약 답을 모르면 모른다고만 말하고 답을 지어내려고 하지 마십시오.
        답변은 최대 세 문장으로 하고 가능한 한 간결하게 유지하십시오.
        {summaries}
        질문: {question}
        도움이 되는 답변:"""

        messages = [
            SystemMessagePromptTemplate.from_template(system_template),
            HumanMessagePromptTemplate.from_template("{question}")
        ]
        # prompt 내에 변수처럼 쓸 수 있게끔 해두는 장치
        prompt = ChatPromptTemplate.from_messages(messages)
        
        chain_type_kwargs = {"prompt": prompt}

        llm = ChatOpenAI(model_name="gpt-3.5-turbo-16k", temperature=0)  # Modify model_name if you have access to GPT-4
        model_name = "jhgan/ko-sroberta-multitask"
        model_kwargs = {'device': 'cpu'}
        encode_kwargs = {'normalize_embeddings': False}
        
        hf = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs=model_kwargs,
            encode_kwargs=encode_kwargs,
            # cache_dir=True
        )

        vectordb_hf = Chroma(persist_directory="C:/Users/user/Desktop/final_project/big_project/media/embedding_files/1_kcards", embedding_function=hf)
        retriever_hf = vectordb_hf.as_retriever()
        
        chain = RetrievalQAWithSourcesChain.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever = retriever_hf,
            # retriever = retriever,
            return_source_documents=False, # source document를 return
            chain_type_kwargs=chain_type_kwargs # langchain type argument에다가 지정한 prompt를 넣어줌, 별도의 prompt를 넣음
        )
        
        query = input_data
        result = chain(query)
        print(result['answer'])
        
        # 빈 문자열 제거
        selected_clients = [id for id in selected_clients if id]
        selected_files = [id for id in selected_files if id]

        clients = Client.objects.filter(id__in=selected_clients)
        files = CompanyFile.objects.filter(id__in=selected_files)

        return render(request, 'client/start_tm.html', {'data': input_data, 'selectedClients': clients, 'selectedFiles': files})

    return render(request, 'client/selected_items.html', {'data': input_data, 'selectedClients': selected_clients, 'selectedFiles': selected_files})
