import json
from urllib.request import Request as url_request
import facebook # Facebook API sdk
import logging
logger = logging.getLogger('system')

# Django 
from django.shortcuts import render, redirect, reverse
from django.http import HttpResponse, JsonResponse
from django.views.generic import ListView, DetailView, View
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm, AdminPasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.backends import ModelBackend
from django.contrib import messages 
from django.conf import settings
from django.views.generic.edit import CreateView, UpdateView, DeleteView, FormView
from django.utils.decorators import method_decorator

# Django extensions
from social_django.models import UserSocialAuth
from rest_framework.views import APIView
from rest_framework.response import Response 
from rest_framework import status 
from rest_framework import generics
from rest_framework import permissions 
from rest_framework.decorators import api_view
from rest_framework.reverse import reverse as api_reverse

# Local
from system.models import Recipe, Ingredient
from system.forms import UserForm, UserRegistrationForm, UserInfoForm, ProfileInfoForm
from system.serializers import RecipeSerializer, RecipeDetailSerializer, UserSerializer, UserDetailSerializer, RecipeCreateSerializer


############################################################
# Users
############################################################

class UserList(ListView):
	model = User
	template_name = 'system/user_list.html'

	def get_queryset(self):
		return User.objects.all()

	def get_context_data(self, **kwargs):
		# Call the base implementation first to get context
		context = super(UserList, self).get_context_data(**kwargs)
		context = add_user_recipes_to_context(self.request.user, context)
		return context


class UserDetail(DetailView):
	model = User
	template_name = 'system/user_detail.html'
	slug_field = 'username' # slug is in url, ex: users/<username>
	context_object_name = 'viewed_user'

	def get_context_data(self, **kwargs):
		# Call the base implementation first to get context
		context = super(UserDetail, self).get_context_data(**kwargs)

		viewed_user = context['viewed_user']
		try: 
			facebook_login = viewed_user.social_auth.get(provider='facebook')
			context['facebook_login'] = facebook_login

			oauth_token = facebook_login.extra_data['access_token']
			graph = facebook.GraphAPI(access_token=oauth_token)

			profile = graph.get_object("me")
			picture = graph.get_connections("me", "picture")

			context['profile_pics_url'] = picture['url']
		except UserSocialAuth.DoesNotExist:
			facebook_login = None

		context['viewed_user_created_recipes'] = viewed_user.profile.created_recipes.all()
		context['viewed_user_saved_recipes'] = viewed_user.profile.saved_recipes.all()

		context = add_user_recipes_to_context(self.request.user, context)
		return context



class UserRegistrationView(FormView):
	form_class = UserRegistrationForm
	template_name = 'users/register.html'
	success_url = '/' # reverse('system:home')

	def form_valid(self, form):
		form.save()
		username = form.cleaned_data.get('username')
		password = form.cleaned_data.get('password1')

		user = authenticate(username=username, password=password)
		if user is not None: 
			login(self.request, user)
			messages.info(self.request, "Logged into new account for {}.".format(username))
		else:
			messages.error(self.request, "Created account, but failed to login {}.".format(username))

		return super(UserRegistrationView, self).form_valid(form)

	def get_context_data(self, **kwargs):
		# Call the base implementation first to get a context
		context = super(UserRegistrationView, self).get_context_data(**kwargs)
		return context


# def login_user(request):
# 	return render(request, 'users/login.html')

def logout_user(request):
	logout(request)
	return redirect('/')

@login_required
def delete_user(request):
	user = request.user
	try:
		user.delete()
		messages.info(request, "Successfully deleted user {}.".format(user.username))
	except Exception as e:
		messages.error(request, "Failed to delete user {}.".format(user.username))

	return redirect('home')


# Page for a user to view and update their profile
@login_required
def update_profile(request):
	user = request.user
	template_name = 'users/update_profile.html'
	context = {}

	if request.method == 'POST':
		# Process submitted form
		user_form = UserInfoForm(request.POST, instance=user)
		profile_form = ProfileInfoForm(request.POST, instance=user.profile)
		context['user_form'] = user_form
		context['profile_form'] = profile_form

		if user_form.is_valid() and profile_form.is_valid():
			user_form.save()
			profile_form.save()
			messages.success(request, 'Profile updated.')
			return redirect('profile')
		else:
			messages.error(request, 'Please correct the errors below.')

	else: 
		# Display form with existing info 
		user_form = UserInfoForm(instance=user)
		profile_form = ProfileInfoForm(instance=user.profile)
		context['user_form'] = user_form
		context['profile_form'] = profile_form

		try: 
			facebook_login = user.social_auth.get(provider='facebook')

			oauth_token = facebook_login.extra_data['access_token']
			graph = facebook.GraphAPI(access_token=oauth_token)
			profile = graph.get_object("me")

			picture = graph.get_connections("me", "picture")
			context['profile_pics_url'] = picture['url']


		except UserSocialAuth.DoesNotExist:
			facebook_login = None

		can_disconnect = (user.social_auth.count() > 1 or user.has_usable_password())
		context['facebook_login'] = facebook_login
		context['can_disconnect'] = can_disconnect

	return render(request, template_name, context)



# AJAX request to add to a user's saved recipes
@login_required
def add_to_user_saved_recipes(request):
	response_data = {}
	if request.method == 'POST':
		recipe_id = request.POST.get('recipe_id')
		try:
			recipe = Recipe.objects.get(id=recipe_id)
		except Recipe.DoesNotExist:
			recipe = None

		user_profile = request.user.profile

		# Like the recipe. If it is already liked, unlike it. 
		if user_profile.saved_recipes.filter(pk=recipe.pk).exists():
			user_profile.saved_recipes.remove(recipe)
			response_data['message'] = 'Removed recipe %s from %s\'s saved recipes' % (recipe_id, request.user.username)
		else:
			user_profile.saved_recipes.add(recipe)
			response_data['message'] = 'Added recipe %s to %s\'s saved recipes' % (recipe_id, request.user.username)

	else:
		response_data['message'] = 'Submission type needs to be POST.'
	
	return JsonResponse(response_data)




@login_required
def change_password(request):
	if request.user.has_usable_password():
		PasswordForm = PasswordChangeForm
	else:
		PasswordForm = AdminPasswordChangeForm

	if request.method == 'POST':
		form = PasswordForm(request.user, request.POST)
		if form.is_valid():
			form.save()
			update_session_auth_hash(request, form.user)
			messages.success(request, 'Your password was successfully updated.')
			return redirect('home')
		else:
			messages.error(request, 'Please correct the errors below.')
	else:
		form = PasswordForm(request.user)

	return render(request, 'users/password_reset.html', {'form': form } )


def add_user_recipes_to_context(user, context):
	if user.is_authenticated:
		context['saved_recipes'] = user.profile.saved_recipes.all()
		context['liked_recipes'] = user.profile.liked_recipes.all()
		context['disliked_recipes'] = user.profile.disliked_recipes.all()
	return context


